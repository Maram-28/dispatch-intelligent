"""Authentification — deux implémentations sélectionnées par AUTH_MODE:

- AUTH_MODE=legacy (défaut historique) : JWT HS256 maison, users.json + bcrypt. Code
  intact, conservé le temps de la bascule Keycloak (voir infra/keycloak/README.md).
- AUTH_MODE=keycloak : les tokens sont émis par Keycloak (Authorization Code + PKCE
  côté frontend) ; ce module ne fait plus que les valider via JWKS (RS256), sans
  jamais émettre de JWT lui-même.

Point de compatibilité critique (mode keycloak) : le reste du code (member_profiles.json,
notifications/store.py, sse_manager.subscribe(user_id), sla_watchdog, assigned_to.membre_id)
indexe tout par l'id métier historique (ex. "cherazade_hamdi"). Le `sub` d'un token
Keycloak est un UUID opaque généré par Keycloak — l'identité applicative doit donc
être lue depuis `preferred_username` (le username Keycloak, configuré = id métier
lors de la migration), jamais depuis `sub`.
"""

import os
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List

import bcrypt as _bcrypt
import jwt
import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2AuthorizationCodeBearer
from pydantic import BaseModel

AUTH_MODE = os.environ.get("AUTH_MODE", "legacy")  # "legacy" | "keycloak"

# ─────────────────────────────────────────────
#  Legacy (JWT HS256 maison)
# ─────────────────────────────────────────────

SECRET_KEY = os.environ.get("JWT_SECRET", "lvmh-ticket-jwt-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

USERS_FILE = Path("data/processed/users.json")

# ─────────────────────────────────────────────
#  Keycloak (JWKS / RS256)
# ─────────────────────────────────────────────

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "lvmh-tickets")
KEYCLOAK_FRONTEND_CLIENT_ID = os.environ.get("KEYCLOAK_FRONTEND_CLIENT_ID", "ticket-dispatch-frontend")
KEYCLOAK_ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

_jwks_client: Optional[jwt.PyJWKClient] = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Instancié à la demande (pas au chargement du module) pour ne jamais faire
    d'appel réseau quand AUTH_MODE=legacy. PyJWKClient met en cache les clés
    récupérées — pas de fetch JWKS à chaque requête."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs", cache_keys=True)
    return _jwks_client


if AUTH_MODE == "keycloak":
    oauth2_scheme = OAuth2AuthorizationCodeBearer(
        authorizationUrl=f"{KEYCLOAK_ISSUER}/protocol/openid-connect/auth",
        tokenUrl=f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token",
    )
else:
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


class User(BaseModel):
    id: str
    nom: str
    email: str
    role: str  # "admin" | "agent"
    hashed_password: Optional[str] = None  # non applicable en mode keycloak


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    nom: str
    membre_id: str


_USERS_LOCK = threading.Lock()


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_users() -> List[dict]:
    """Lecture seule, verrouillée."""
    with _USERS_LOCK:
        if not USERS_FILE.exists():
            return []
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)


def _save_users(users: List[dict]) -> None:
    """Écriture seule (remplacement complet), verrouillée + atomique. Pour les cas
    qui n'ont pas besoin de relire l'existant avant d'écrire (ex: bootstrap)."""
    with _USERS_LOCK:
        _atomic_write(USERS_FILE, users)


@contextmanager
def users_transaction():
    """Charge users.json, verrou tenu pour TOUTE la durée du bloc `with`, sauvegarde
    atomique automatique à la sortie normale du bloc. Si une exception est levée à
    l'intérieur du bloc, la sauvegarde n'a pas lieu (rollback implicite).

    Même pattern que profiles_store.py's profiles_transaction() — un load()/save()
    séparés ne suffiraient pas à empêcher une mise à jour perdue entre deux requêtes
    HTTP concurrentes (FastAPI exécute les endpoints synchrones dans un threadpool).

    Usage :
        with users_transaction() as users:
            ...mute `users` (liste de dicts) en place...
    """
    with _USERS_LOCK:
        users = []
        if USERS_FILE.exists():
            with open(USERS_FILE, encoding="utf-8") as f:
                users = json.load(f)
        yield users
        _atomic_write(USERS_FILE, users)


def init_users_from_profiles() -> None:
    """Bootstrap users.json depuis member_profiles.json au premier démarrage.
    N'a de sens qu'en AUTH_MODE=legacy — en mode keycloak, les comptes sont créés
    via scripts/migrate_users_to_keycloak.py, pas ici."""
    if AUTH_MODE != "legacy":
        return
    if USERS_FILE.exists():
        return
    profiles_file = Path("data/processed/member_profiles.json")
    if not profiles_file.exists():
        print("[AUTH] member_profiles.json not found — run POST /profiles/bootstrap first, then restart.")
        return
    with open(profiles_file, encoding="utf-8") as f:
        profiles = json.load(f)
    default_pw = "TicketApp2025!"
    users = [
        {
            "id": p["id"],
            "nom": p.get("nom", p["id"]),
            "email": p.get("email", f"{p['id']}@lvmh.com"),
            "role": "admin" if i == 0 else "agent",
            "hashed_password": hash_password(default_pw),
        }
        for i, p in enumerate(profiles)
    ]
    _save_users(users)
    print(f"\n[AUTH] {len(users)} comptes créés — mot de passe par défaut: {default_pw}")
    print(f"[AUTH] Admin: {users[0]['id']}")
    print(f"[AUTH] Agents: {', '.join(u['id'] for u in users[1:])}\n")


def get_user(user_id: str) -> Optional[User]:
    for u in _load_users():
        if u["id"] == user_id:
            return User(**u)
    return None


def authenticate_user(user_id: str, password: str) -> Optional[User]:
    user = get_user(user_id)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict) -> str:
    payload = {**data, "exp": int(time.time()) + ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _get_current_user_legacy(token: str) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise exc
    except jwt.PyJWTError:
        raise exc
    user = get_user(user_id)
    if not user:
        raise exc
    return user


def _get_current_user_keycloak(token: str) -> User:
    """Valide un access token émis par Keycloak via JWKS (RS256).

    `aud` par défaut de Keycloak est "account" (pas le client id) — on ne le
    vérifie donc pas ; à la place on vérifie `azp` (authorized party), qui doit
    correspondre au client frontend attendu.
    """
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        raise exc

    if payload.get("azp") != KEYCLOAK_FRONTEND_CLIENT_ID:
        raise exc

    user_id = payload.get("preferred_username")
    if not user_id:
        raise exc

    roles = set(payload.get("realm_access", {}).get("roles", []))
    if "admin" in roles:
        role = "admin"
    elif "agent" in roles:
        role = "agent"
    else:
        raise HTTPException(status_code=403, detail="Aucun rôle applicatif (admin/agent) sur ce compte")

    return User(
        id=user_id,
        nom=payload.get("name") or user_id,
        email=payload.get("email") or "",
        role=role,
        hashed_password=None,
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    if AUTH_MODE == "keycloak":
        return _get_current_user_keycloak(token)
    return _get_current_user_legacy(token)


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs",
        )
    return current_user
