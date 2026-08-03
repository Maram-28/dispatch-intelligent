"""
Script de test autonome pour src/auth.py, mode AUTH_MODE=keycloak — entièrement
hors-ligne (pas de Keycloak, pas de backend nécessaires) : on génère une paire
RSA à la volée, on signe de faux tokens avec la clé privée, et on monkeypatche
le JWKS client pour qu'il renvoie la clé publique correspondante, exactement
comme le ferait un vrai serveur Keycloak.

Lancer avec : python tests/test_auth.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from src import auth as auth_module

FAILURES = []


def check(label, expected, actual):
    ok = expected == actual
    status = "OK  " if ok else "FAIL"
    print(f"[{status}] {label}")
    print(f"        attendu : {expected}")
    print(f"        obtenu  : {actual}")
    if not ok:
        FAILURES.append(label)


def check_raises(label, status_code, fn):
    try:
        fn()
        print(f"[FAIL] {label}")
        print(f"        attendu : HTTPException {status_code}")
        print(f"        obtenu  : aucune exception")
        FAILURES.append(label)
    except HTTPException as e:
        ok = e.status_code == status_code
        print(f"[{'OK  ' if ok else 'FAIL'}] {label}")
        print(f"        attendu : HTTPException {status_code}")
        print(f"        obtenu  : HTTPException {e.status_code}")
        if not ok:
            FAILURES.append(label)


_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_public_key)


auth_module._jwks_client = _FakeJWKSClient()  # monkeypatch : pas d'appel réseau JWKS


def make_token(**overrides):
    now = int(time.time())
    payload = {
        "preferred_username": "cherazade_hamdi",
        "name": "Cherazade Hamdi",
        "email": "cherazade.hamdi@lvmh.com",
        "realm_access": {"roles": ["agent"]},
        "azp": auth_module.KEYCLOAK_FRONTEND_CLIENT_ID,
        "iss": auth_module.KEYCLOAK_ISSUER,
        "iat": now,
        "exp": now + 300,
    }
    payload.update(overrides)
    return jwt.encode(payload, _private_key, algorithm="RS256")


print("=" * 70)
print("Scenario 1 : token valide, role agent")
print("=" * 70)
user = auth_module._get_current_user_keycloak(make_token())
check("id == preferred_username (pas sub)", "cherazade_hamdi", user.id)
check("role == agent", "agent", user.role)
check("email correctement extrait", "cherazade.hamdi@lvmh.com", user.email)

print()
print("=" * 70)
print("Scenario 2 : token expire")
print("=" * 70)
expired = make_token(exp=int(time.time()) - 10)
check_raises("token expire -> 401", 401, lambda: auth_module._get_current_user_keycloak(expired))

print()
print("=" * 70)
print("Scenario 3 : mauvais azp (client non attendu)")
print("=" * 70)
wrong_azp = make_token(azp="un-autre-client")
check_raises("azp incorrect -> 401", 401, lambda: auth_module._get_current_user_keycloak(wrong_azp))

print()
print("=" * 70)
print("Scenario 4 : aucun role applicatif (admin/agent) sur le token")
print("=" * 70)
no_role = make_token(realm_access={"roles": ["offline_access", "uma_authorization"]})
check_raises("pas de role admin/agent -> 403", 403, lambda: auth_module._get_current_user_keycloak(no_role))

print()
print("=" * 70)
print("Scenario 5 : role admin prioritaire si admin ET agent presents")
print("=" * 70)
both_roles = make_token(realm_access={"roles": ["agent", "admin"]})
user = auth_module._get_current_user_keycloak(both_roles)
check("admin l'emporte sur agent", "admin", user.role)

print()
print("=" * 70)
if FAILURES:
    print(f"RESULTAT : {len(FAILURES)} echec(s) sur les scenarios : {FAILURES}")
    sys.exit(1)
else:
    print("RESULTAT : tous les scenarios sont valides.")
    sys.exit(0)
