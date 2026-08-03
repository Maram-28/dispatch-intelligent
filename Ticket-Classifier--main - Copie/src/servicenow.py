"""
ServiceNow Integration — Lecture + écriture tickets via REST API.

Utilisé par le webhook POST /webhook/new-ticket (voir src/api.py) pour relire
le sys_id d'un incident à partir de son numéro et y écrire le résultat de la
classification IA (state, work_notes, assigned_to).
"""
import logging
import os

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

AUTH = HTTPBasicAuth(os.getenv("SN_USER", ""), os.getenv("SN_PASSWORD", ""))
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
SN = os.getenv("SN_INSTANCE", "").rstrip("/")  # https://devXXXXX.service-now.com

# Généreux par défaut : un PATCH qui change impact/urgency peut déclencher une
# Business Rule ServiceNow synchrone (ex. notification manager) qui ne rend la
# main qu'après son propre traitement — voir webhook_priority_changed dans api.py.
TIMEOUT = 30


def get_ticket_sys_id(numero: str) -> str | None:
    """Retourne le sys_id ServiceNow d'un incident depuis son numéro."""
    try:
        r = requests.get(
            f"{SN}/api/now/table/incident",
            params={"sysparm_query": f"number={numero}", "sysparm_fields": "sys_id"},
            auth=AUTH, headers=HEADERS, timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error("[ServiceNow] get_ticket_sys_id(%s) a échoué : %s", numero, e)
        return None
    res = r.json().get("result", [])
    return res[0]["sys_id"] if res else None


def get_user_sys_id(email: str) -> str | None:
    """Retourne le sys_id de l'utilisateur ServiceNow correspondant à cet email."""
    if not email:
        return None
    try:
        r = requests.get(
            f"{SN}/api/now/table/sys_user",
            params={"sysparm_query": f"email={email}", "sysparm_fields": "sys_id"},
            auth=AUTH, headers=HEADERS, timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error("[ServiceNow] get_user_sys_id(%s) a échoué : %s", email, e)
        return None
    res = r.json().get("result", [])
    return res[0]["sys_id"] if res else None


def update_ticket(numero: str, payload: dict, display_value: bool = False) -> bool:
    """Met à jour un incident ServiceNow (PATCH) à partir de son numéro.

    display_value=True envoie sysparm_input_display_value=true : les valeurs du
    payload sont alors interprétées comme des libellés affichés (traduits) plutôt
    que des valeurs techniques — utile pour un champ choice personnalisé (ex.
    `hold_reason`) dont on ne connaît pas les codes techniques à l'avance. Ce mode
    s'applique à TOUT le payload de l'appel, donc ne jamais l'utiliser sur un appel
    qui mélange aussi des valeurs techniques déjà connues (ex. `state`, un sys_id) :
    faire des appels PATCH séparés dans ce cas.
    """
    sys_id = get_ticket_sys_id(numero)
    if not sys_id:
        logger.error("[ServiceNow] update_ticket(%s) : ticket introuvable", numero)
        return False
    params = {"sysparm_input_display_value": "true"} if display_value else None
    try:
        r = requests.patch(
            f"{SN}/api/now/table/incident/{sys_id}",
            json=payload, params=params, auth=AUTH, headers=HEADERS, timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error("[ServiceNow] update_ticket(%s) a échoué : %s", numero, e)
        return False
    if r.status_code != 200:
        logger.error(
            "[ServiceNow] update_ticket(%s) : HTTP %s — %s", numero, r.status_code, r.text[:300]
        )
    return r.status_code == 200
