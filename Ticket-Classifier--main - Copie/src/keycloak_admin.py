"""
Keycloak Admin REST — utilisé uniquement en AUTH_MODE=keycloak, par les endpoints
de gestion des comptes (GET /users, PATCH /users/{id}/role), par sla_watchdog
(liste des admins à notifier) et par scripts/migrate_users_to_keycloak.py.

Authentification côté service : client confidentiel "ticket-dispatch-backend"
(client_credentials grant, service account) — jamais de credentials utilisateur
ici, contrairement à src/servicenow.py qui utilise un compte technique en Basic
Auth ; le principe (module requests dédié, jamais d'appel direct ailleurs dans le
code) est le même.
"""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "lvmh-tickets")
BACKEND_CLIENT_ID = os.environ.get("KEYCLOAK_BACKEND_CLIENT_ID", "ticket-dispatch-backend")
BACKEND_CLIENT_SECRET = os.environ.get("KEYCLOAK_BACKEND_CLIENT_SECRET", "")

TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
ADMIN_BASE = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
TIMEOUT = 10

_service_token_cache = {"token": None, "expires_at": 0.0}


def _get_service_token() -> str:
    """Token du service account (client_credentials), mis en cache jusqu'à ~10s
    avant son expiration réelle — évite un aller-retour Keycloak à chaque appel
    admin sans jamais réutiliser un token déjà expiré."""
    now = time.time()
    if _service_token_cache["token"] and now < _service_token_cache["expires_at"]:
        return _service_token_cache["token"]

    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": BACKEND_CLIENT_ID,
            "client_secret": BACKEND_CLIENT_SECRET,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    _service_token_cache["token"] = body["access_token"]
    _service_token_cache["expires_at"] = now + body.get("expires_in", 60) - 10
    return _service_token_cache["token"]


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_get_service_token()}"}


def list_users_with_roles() -> list[dict]:
    """Retourne [{id, nom, email, role}] pour tous les utilisateurs du realm.
    `role` = "admin" si l'utilisateur a le realm role admin, sinon "agent" si le
    role agent est présent, sinon None (compte sans rôle applicatif assigné)."""
    r = requests.get(f"{ADMIN_BASE}/users", headers=_auth_headers(), params={"max": 500}, timeout=TIMEOUT)
    r.raise_for_status()
    users = r.json()

    result = []
    for u in users:
        roles_r = requests.get(
            f"{ADMIN_BASE}/users/{u['id']}/role-mappings/realm", headers=_auth_headers(), timeout=TIMEOUT
        )
        roles_r.raise_for_status()
        role_names = {rr["name"] for rr in roles_r.json()}
        role = "admin" if "admin" in role_names else ("agent" if "agent" in role_names else None)
        nom = " ".join(part for part in (u.get("firstName"), u.get("lastName")) if part) or u["username"]
        result.append({
            "id": u["username"],
            "nom": nom,
            "email": u.get("email", ""),
            "role": role,
        })
    return result


def _get_realm_role(role_name: str) -> dict:
    r = requests.get(f"{ADMIN_BASE}/roles/{role_name}", headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _get_user_id_by_username(username: str) -> str | None:
    r = requests.get(
        f"{ADMIN_BASE}/users", headers=_auth_headers(), params={"username": username, "exact": "true"}, timeout=TIMEOUT
    )
    r.raise_for_status()
    users = r.json()
    return users[0]["id"] if users else None


def set_user_role(username: str, new_role: str) -> bool:
    """Retire admin/agent existants puis assigne new_role — un seul rôle applicatif
    actif à la fois, cohérent avec le modèle binaire admin|agent d'aujourd'hui."""
    user_id = _get_user_id_by_username(username)
    if not user_id:
        return False

    current_r = requests.get(
        f"{ADMIN_BASE}/users/{user_id}/role-mappings/realm", headers=_auth_headers(), timeout=TIMEOUT
    )
    current_r.raise_for_status()
    to_remove = [rr for rr in current_r.json() if rr["name"] in ("admin", "agent")]
    if to_remove:
        requests.request(
            "DELETE",
            f"{ADMIN_BASE}/users/{user_id}/role-mappings/realm",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=to_remove,
            timeout=TIMEOUT,
        ).raise_for_status()

    new_role_repr = _get_realm_role(new_role)
    requests.post(
        f"{ADMIN_BASE}/users/{user_id}/role-mappings/realm",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=[new_role_repr],
        timeout=TIMEOUT,
    ).raise_for_status()
    return True


def _split_nom(nom: str) -> tuple[str, str]:
    """`nom` dans users.json est un nom complet ("Cherazade HAMDI", "Mohamed Rabeh
    BOUKAHLA") sans champs prénom/nom séparés. Le User Profile par défaut de
    Keycloak exige firstName ET lastName non vides (sinon l'action requise
    dynamique VERIFY_PROFILE bloque le compte — constaté en test : le direct
    grant échoue avec "Account is not fully set up" pour tout utilisateur créé
    sans lastName). Heuristique : dernier mot = nom de famille, le reste = prénom."""
    parts = nom.strip().split(" ")
    if len(parts) < 2:
        return nom, nom
    return " ".join(parts[:-1]), parts[-1]


def create_user(username: str, email: str, nom: str, role: str, temp_password: str) -> bool:
    """Crée un utilisateur avec un mot de passe temporaire + UPDATE_PASSWORD forcé
    au premier login. Utilisé uniquement par scripts/migrate_users_to_keycloak.py.
    Idempotent : renvoie False sans erreur si le username existe déjà."""
    if _get_user_id_by_username(username):
        return False

    first_name, last_name = _split_nom(nom)
    r = requests.post(
        f"{ADMIN_BASE}/users",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json={
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": True,
            "requiredActions": ["UPDATE_PASSWORD"],
            "credentials": [{"type": "password", "value": temp_password, "temporary": True}],
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    user_id = _get_user_id_by_username(username)
    role_repr = _get_realm_role(role)
    requests.post(
        f"{ADMIN_BASE}/users/{user_id}/role-mappings/realm",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=[role_repr],
        timeout=TIMEOUT,
    ).raise_for_status()
    return True


def send_password_reset_email(username: str) -> bool:
    """Déclenche l'email Keycloak "définir votre mot de passe" (requiert le SMTP
    du realm configuré — voir infra/keycloak/README.md)."""
    user_id = _get_user_id_by_username(username)
    if not user_id:
        return False
    r = requests.put(
        f"{ADMIN_BASE}/users/{user_id}/execute-actions-email",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=["UPDATE_PASSWORD"],
        timeout=TIMEOUT,
    )
    return r.status_code in (200, 204)


def get_admin_usernames() -> list[str]:
    """Équivalent Keycloak de `[u['id'] for u in _load_users() if u['role']=='admin']`
    (legacy) — utilisé par sla_watchdog._get_managers()."""
    r = requests.get(f"{ADMIN_BASE}/roles/admin/users", headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return [u["username"] for u in r.json()]
