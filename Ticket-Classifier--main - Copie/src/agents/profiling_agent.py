"""
LVMH Power BI Ticket Dispatch
EY Data Team - Module 2 Part 1: Profiling Agent (Python pur, sans LLM)

Responsabilités :
  - Bootstrap : depuis incident-10000.xlsx, seed uniquement l'identité et les compétences/
    spécialisations (utilisées par le Scorer pour match_competence/brand_affinity) ; ne seed
    PLUS les métriques de performance (voir _build_profiles)
  - get_profiles_for_scorer() : fournit les profils enrichis (charge_normalisee) au Scorer
  - update_after_resolution()  : seule source des métriques de performance (total tickets,
    résolution moyenne/médiane, taux de réouverture, score) — alimentée par les résolutions
    réelles de tickets dans l'app (temps SLA réel : started_at - pauses), jamais par l'Excel
  - Auto-découverte de compétences (>85% succès sur min 5 tickets d'une catégorie)
"""

import json
import re
import statistics
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import pandas as pd

from src.agents import profiles_store

# ─────────────────────────────────────────────
#  CONSTANTES ÉQUIPE
# ─────────────────────────────────────────────

TEAM_MEMBERS = [
    {"id": "cherazade_hamdi",         "nom": "Cherazade HAMDI",         "email": "chamdi-ext@pcis.lvmh-pc.com"},
    {"id": "leila_skouri",            "nom": "Leila SKOURI",            "email": "lskouri-ext@pcis.lvmh-pc.com"},
    {"id": "mariem_el_ouekdi",        "nom": "Mariem EL OUEKDI",        "email": "melouekdi-ext@pcis.lvmh-pc.com"},
    {"id": "mohamed_rabeh_boukahla",  "nom": "Mohamed Rabeh BOUKAHLA",  "email": "mboukahla-ext@pcis.lvmh-pc.com"},
    {"id": "mohamed_salah_baccouche", "nom": "Mohamed Salah BACCOUCHE", "email": "mbaccouche-ext@pcis.lvmh-pc.com"},
]

DATA_FILE = Path("data/raw/incident-10000.xlsx")

# ─────────────────────────────────────────────
#  MAPS COMPÉTENCES
# ─────────────────────────────────────────────

SOUS_CAT_TO_SKILLS: dict[str, list[str]] = {
    "Datas":       ["Data Engineering", "Data Analysis"],
    "Accès":       ["Access Management", "Security"],
    "Logiciel":    ["Software Support"],
    "Application": ["Application Support"],
    "Bug":         ["Debugging", "Quality Assurance"],
    "Evolution":   ["Development", "Project Management"],
    "Sécurité":    ["Security", "Compliance"],
    "Matériel":    ["Hardware Support"],
    "Production":  ["Production Support"],
}

SERVICE_KEYWORD_TO_SKILL: dict[str, str] = {
    "powerbi":   "Power BI",
    "power bi":  "Power BI",
    "crm":       "CRM",
    "retail":    "Retail Analytics",
    "datahub":   "Data Engineering",
    "supply":    "Supply Chain",
    "media":     "Media Analytics",
    "self bi":   "Self-Service BI",
    "scorecard": "Reporting",
}

# Auto-découverte : catégorie → compétence émergente
CATEGORY_TO_SKILL: dict[str, str] = {
    "Incident":               "Incident Management",
    "Demande":                "Request Fulfillment",
    "Assistance":             "User Support",
    "Changement applicatif":  "Change Management",
    "Problème applicatif":    "Problem Management",
}

# ─────────────────────────────────────────────
#  HELPERS INTERNES
# ─────────────────────────────────────────────

def _extract_email(value: str) -> str | None:
    """Extrait l'email depuis le format 'Nom Prenom [email | FR]'."""
    if not isinstance(value, str):
        return None
    m = re.search(r'\[([^|\s\]]+)', value)
    return m.group(1).lower().strip() if m else None


def _clean_offre(value: str) -> str | None:
    """Nettoie 'NOM DU SERVICE [WW | BU]' -> 'NOM DU SERVICE'."""
    if not isinstance(value, str):
        return None
    v = re.sub(r'\s*\[[^\]]*\]\s*$', '', value).strip()
    return v or None


def _infer_competences(sous_cats: list, services: list) -> list:
    skills: set[str] = {"Power BI"}
    for sc in sous_cats:
        for key, vals in SOUS_CAT_TO_SKILLS.items():
            if key.lower() in sc.lower():
                skills.update(vals)
    svc_lower = " ".join(services).lower()
    for keyword, skill in SERVICE_KEYWORD_TO_SKILL.items():
        if keyword in svc_lower:
            skills.add(skill)
    return sorted(skills)


def _compute_score(stats: dict, all_stats: list) -> float:
    """Score 0-100 : rapidité×0.50 + volume×0.30 + qualité (respect SLA)×0.20."""
    medians = [s["resolution_median_h"] for s in all_stats if s["resolution_median_h"] > 0]
    max_med = max(medians) if medians else 1.0
    rapidite = (1.0 - stats["resolution_median_h"] / max_med) if stats["resolution_median_h"] > 0 else 0.5

    max_vol = max((s["total_tickets"] for s in all_stats), default=1) or 1
    volume = stats["total_tickets"] / max_vol

    qualite = (stats["taux_respect_sla_pct"] / 100.0) if stats["total_tickets"] > 0 else 0.5
    return round((rapidite * 0.50 + volume * 0.30 + qualite * 0.20) * 100, 1)


def _recompute_score(profile: dict, all_profiles: list) -> float:
    """Recalcule le score depuis un profil (utilisé post-résolution)."""
    medians = [
        p["metriques"]["resolution_median_heures"]
        for p in all_profiles
        if p["metriques"]["resolution_median_heures"] > 0
    ]
    max_med = max(medians) if medians else 1.0
    median  = profile["metriques"]["resolution_median_heures"]
    rapidite = (1.0 - median / max_med) if median > 0 else 0.5

    max_vol = max(p["metriques"]["total_tickets_historique"] for p in all_profiles) or 1
    volume  = profile["metriques"]["total_tickets_historique"] / max_vol

    total = profile["metriques"]["total_tickets_historique"]
    qualite = (profile["metriques"]["taux_respect_sla_pct"] / 100.0) if total > 0 else 0.5
    return round((rapidite * 0.50 + volume * 0.30 + qualite * 0.20) * 100, 1)


def _check_competence_discovery(profile: dict) -> list[str]:
    """
    Retourne les nouvelles compétences découvertes.
    Règle : >85% succès sur minimum 5 tickets d'une catégorie.
    """
    hist     = profile.get("historique_resolutions", {}).get("par_categorie", {})
    existing = set(profile.get("competences", []))
    new_skills = []

    for cat, counts in hist.items():
        total  = counts.get("total", 0)
        succes = counts.get("succes", 0)
        if total >= 5 and (succes / total) >= 0.85:
            skill = CATEGORY_TO_SKILL.get(cat)
            if skill and skill not in existing:
                new_skills.append(skill)

    return new_skills

# ─────────────────────────────────────────────
#  CALCUL DES STATISTIQUES DEPUIS L'EXCEL
# ─────────────────────────────────────────────

def _compute_member_stats() -> list:
    """Lit incident-10000.xlsx et calcule toutes les métriques par membre."""
    df = pd.read_excel(DATA_FILE, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    group_col = "Groupe d'affectation"
    if group_col not in df.columns:
        raise RuntimeError(f"Colonne '{group_col}' introuvable. Disponibles : {list(df.columns[:20])}")

    df = df[df[group_col].str.contains(r"WW\s*-?\s*POWERBI\s*-?\s*L2", case=False, na=False, regex=True)].copy()

    # "Offre de services" (catalogue plus granulaire) prime sur "Service"
    # (regroupement macro dans les exports récents) quand elle est renseignée.
    if "Offre de services" in df.columns:
        offre = df["Offre de services"].apply(_clean_offre)
        df["Service"] = offre.where(offre.notna(), df["Service"]) if "Service" in df.columns else offre

    all_stats = []
    for member in TEAM_MEMBERS:
        target_email = member["email"].lower()
        sub = df[df["Assignée à"].apply(lambda v: _extract_email(v) == target_email)]
        n   = len(sub)

        if n == 0:
            all_stats.append({
                "member": member,
                "total_tickets": 0,
                "resolution_moy_h": 0.0,
                "resolution_median_h": 0.0,
                "priority_breakdown":         {"P1_critique": 0, "P2_majeure": 0, "P3_mineure": 0, "P4_standard": 0},
                "taux_resolution_par_priorite": {"P1": None, "P2": None, "P3": None, "P4": None},
                "temps_moyen_par_categorie":    {},
                "top_services": [],
                "top_sous_categories": [],
                "top_categories": [],
                "nb_reaffectations_total": 0,
                "historique_resolutions": {"par_categorie": {}, "par_priorite": {}},
            })
            continue

        # ── Temps de résolution global ──
        res_h = pd.Series(dtype=float)
        if "Temps de résolution" in sub.columns:
            res_h    = pd.to_numeric(sub["Temps de résolution"], errors="coerce").dropna() / 3600
            moy_h    = round(float(res_h.mean()),   2) if len(res_h) else 0.0
            median_h = round(float(res_h.median()), 2) if len(res_h) else 0.0
        else:
            moy_h = median_h = 0.0

        # ── Réouvertures ──
        reouv = pd.Series(0, index=sub.index)
        if "Nombre de réouvertures" in sub.columns:
            reouv = pd.to_numeric(sub["Nombre de réouvertures"], errors="coerce").fillna(0)

        # ── Priorités : breakdown + taux de succès ──
        prio_breakdown = {"P1_critique": 0, "P2_majeure": 0, "P3_mineure": 0, "P4_standard": 0}
        prio_taux      = {"P1": None, "P2": None, "P3": None, "P4": None}
        hist_prio      = {}

        if "Priorité" in sub.columns:
            prio_series = sub["Priorité"].fillna("")
            for p_key, p_start, p_bk in [
                ("P1", "1", "P1_critique"),
                ("P2", "2", "P2_majeure"),
                ("P3", "3", "P3_mineure"),
                ("P4", "4", "P4_standard"),
            ]:
                mask  = prio_series.str.startswith(p_start)
                total = int(mask.sum())
                prio_breakdown[p_bk] = total
                if total > 0:
                    success        = int((mask & (reouv == 0)).sum())
                    prio_taux[p_key] = round(success / total, 3)
                    hist_prio[p_key] = {"total": total, "succes": success}

        # ── Temps moyen par catégorie + historique ──
        temps_par_cat = {}
        hist_cat      = {}

        if "Catégorie" in sub.columns:
            cat_series = sub["Catégorie"].dropna()
            for cat in cat_series.unique():
                mask    = sub["Catégorie"] == cat
                cat_sub = sub[mask]
                total   = int(mask.sum())
                success = int((mask & (reouv == 0)).sum())

                if "Temps de résolution" in sub.columns:
                    t = pd.to_numeric(cat_sub["Temps de résolution"], errors="coerce").dropna() / 3600
                    temps_par_cat[cat] = round(float(t.mean()), 2) if len(t) else None
                hist_cat[cat] = {"total": total, "succes": success}

        # ── Top services / sous-catégories / catégories ──
        top_svcs = sub["Service"].dropna().value_counts().head(5).index.tolist()         if "Service"        in sub.columns else []
        top_scs  = sub["Sous-catégorie"].dropna().value_counts().head(3).index.tolist()  if "Sous-catégorie" in sub.columns else []
        top_cats = sub["Catégorie"].dropna().value_counts().head(3).index.tolist()        if "Catégorie"      in sub.columns else []

        nb_reaffs = 0
        if "Nombre de réaffectations" in sub.columns:
            nb_reaffs = int(pd.to_numeric(sub["Nombre de réaffectations"], errors="coerce").fillna(0).sum())

        all_stats.append({
            "member": member,
            "total_tickets": n,
            "resolution_moy_h": moy_h,
            "resolution_median_h": median_h,
            "priority_breakdown":          prio_breakdown,
            "taux_resolution_par_priorite": prio_taux,
            "temps_moyen_par_categorie":    temps_par_cat,
            "top_services":        top_svcs,
            "top_sous_categories": top_scs,
            "top_categories":      top_cats,
            "nb_reaffectations_total": nb_reaffs,
            "historique_resolutions": {"par_categorie": hist_cat, "par_priorite": hist_prio},
        })

    return all_stats


def _zero_metriques() -> dict:
    """Métriques de performance de départ pour un membre sans historique live (voir _build_profiles)."""
    return {
        "total_tickets_historique":    0,
        "resolution_moy_heures":       0.0,
        "resolution_median_heures":    0.0,
        "resolution_times_h":         [],
        "repartition_priorites":       {"P1_critique": 0, "P2_majeure": 0, "P3_mineure": 0, "P4_standard": 0},
        "taux_resolution_par_priorite": {"P1": None, "P2": None, "P3": None, "P4": None},
        "temps_moyen_par_categorie":    {},
        "taux_respect_sla_pct":         0.0,
        "nb_reaffectations_total":      0,
    }


def _build_profiles(all_stats: list) -> list:
    """Construit la liste de profils JSON finaux.

    Seuls l'identité et competences/specialisations viennent de l'Excel (via all_stats).
    Les métriques de performance (metriques, historique_resolutions, score_performance) ne
    sont JAMAIS (re)calculées depuis l'Excel ici : elles sont exclusivement alimentées par
    update_after_resolution() au fil des résolutions réelles de tickets dans l'app (temps
    SLA réel, pas l'Excel). Un membre déjà présent dans member_profiles.json garde ses
    métriques live telles quelles — bootstrap reste donc sûr à ré-exécuter (ex. onboarder un
    nouveau membre) sans écraser la progression déjà accumulée des autres ; seul un membre
    tout nouveau démarre à zéro.
    """
    avail_map = {a["id"]: a for a in profiles_store.load_availability().get("members", [])}
    try:
        prior_profiles = {p["id"]: p for p in profiles_store.load_profiles()}
    except FileNotFoundError:
        prior_profiles = {}  # premier bootstrap : aucun profil existant à préserver

    profiles = []
    for stats in all_stats:
        m     = stats["member"]
        av    = avail_map.get(m["id"], {})
        prior = prior_profiles.get(m["id"])

        if prior:
            metriques         = prior["metriques"]
            historique        = prior["historique_resolutions"]
            score_performance = prior["score_performance"]
            charge_actuelle   = prior["charge_actuelle"]
        else:
            zero_stats        = {"resolution_median_h": 0.0, "total_tickets": 0, "taux_respect_sla_pct": 0.0}
            metriques         = _zero_metriques()
            historique        = {"par_categorie": {}, "par_priorite": {}}
            score_performance = _compute_score(zero_stats, [zero_stats])
            charge_actuelle   = 0

        profiles.append({
            "id":     m["id"],
            "nom":    m["nom"],
            "email":  m["email"],
            "groupe": "WW - POWERBI - L2",
            "competences": _infer_competences(stats["top_sous_categories"], stats["top_services"]),
            "specialisations": {
                "services":        stats["top_services"],
                "sous_categories": stats["top_sous_categories"],
                "categories":      stats["top_categories"],
            },
            "metriques": metriques,
            "historique_resolutions": historique,
            "charge_actuelle":   charge_actuelle,
            "disponible":        av.get("disponible", True),
            "score_performance": score_performance,
        })
    return profiles

# ─────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────

def run_bootstrap() -> list:
    """
    (Re)calcule identité + compétences/spécialisations depuis l'Excel et sauvegarde.
    Les métriques de performance ne sont plus dérivées de l'Excel (voir _build_profiles) :
    un membre déjà connu garde ses métriques live, un nouveau membre démarre à zéro.
    Appelé par POST /profiles/bootstrap et __main__.
    """
    stats    = _compute_member_stats()
    profiles = _build_profiles(stats)
    profiles_store.save_profiles(profiles)
    return profiles

# Alias pour compatibilité avec l'API existante
_direct_bootstrap = run_bootstrap


def run_update(delta: dict) -> dict:
    """
    Met à jour charge_actuelle d'un membre (+1 ou -1).
    delta = {"assignee_id": "cherazade_hamdi", "delta": 1}
    """
    assignee_id = delta.get("assignee_id")
    d = int(delta.get("delta", 0))

    with profiles_store.profiles_transaction() as profiles:
        for profile in profiles:
            if profile["id"] == assignee_id:
                profile["charge_actuelle"] = max(0, profile["charge_actuelle"] + d)
                break
        else:
            raise ValueError(f"Membre '{assignee_id}' introuvable.")
        result = next(p for p in profiles if p["id"] == assignee_id)

    return result


def get_profiles_for_scorer() -> list:
    """
    Retourne les profils enrichis avec charge_normalisee (0→1).
    Utilisé par le Scorer Agent au moment du dispatch.
    La normalisation est relative à la charge max de l'équipe.
    """
    profiles = profiles_store.load_profiles()

    charges   = [p["charge_actuelle"] for p in profiles]
    max_charge = max(charges) if max(charges) > 0 else 1

    enriched = []
    for p in profiles:
        enriched.append({
            **p,
            "charge_normalisee": round(p["charge_actuelle"] / max_charge, 3),
        })

    return enriched


def update_after_resolution(membre_id: str, ticket: dict, reopened: bool = False, sla_respected: bool = True) -> dict:
    """
    Met à jour le profil d'un membre après résolution d'un ticket.
    Déclenche aussi la vérification d'auto-découverte de compétences.

    ticket = {
        "categorie":        "Incident",
        "sous_categorie":   "Bug",
        "service":          "O365-PowerBI",
        "priorite":         "P1",          # "P1" | "P2" | "P3" | "P4"
        "resolution_time_h": 2.5
    }
    reopened : True si le ticket a été réouvert avant résolution finale.
    sla_respected : True si le ticket a été résolu avant sla_deadline (sla_engine.on_status_change
        calcule déjà ce verdict côté appelant, "sla_breached" ; défaut True pour les appelants sans
        contexte SLA, ex. l'endpoint générique /profiles/{id}/resolve).
    """
    with profiles_store.profiles_transaction() as profiles:
        profile = next((p for p in profiles if p["id"] == membre_id), None)
        if not profile:
            raise ValueError(f"Membre '{membre_id}' introuvable.")

        m       = profile["metriques"]
        hist    = profile.setdefault("historique_resolutions", {"par_categorie": {}, "par_priorite": {}})
        n       = m["total_tickets_historique"]
        cat     = ticket.get("categorie", "")
        prio    = ticket.get("priorite", "")          # "P1" / "P2" / "P3" / "P4"
        res_h   = float(ticket.get("resolution_time_h", 0))
        success = not reopened

        # ── Temps de résolution moyen + médian global ──
        if res_h > 0:
            m["resolution_moy_heures"] = round(
                (m["resolution_moy_heures"] * n + res_h) / (n + 1), 2
            )
            # Médiane non calculable par moyenne glissante : on garde une fenêtre bornée des
            # derniers temps de résolution (même logique que classifications_db.json/
            # notifications.json) et on la recalcule à chaque résolution.
            times = m.setdefault("resolution_times_h", [])
            times.append(round(res_h, 2))
            if len(times) > 500:
                del times[: len(times) - 500]
            m["resolution_median_heures"] = round(statistics.median(times), 2)

        # ── Total tickets ──
        m["total_tickets_historique"] = n + 1

        # ── Taux de respect SLA (rolling) ──
        # setdefault (pas une simple lecture) : champ absent des profils déjà remis à zéro
        # sur disque avant l'ajout de cette métrique — auto-guérison à la première écriture.
        total_ok = round(m.setdefault("taux_respect_sla_pct", 0.0) / 100 * n)
        if sla_respected:
            total_ok += 1
        m["taux_respect_sla_pct"] = round(total_ok / (n + 1) * 100, 2)

        # ── Temps moyen par catégorie ──
        if cat and res_h > 0:
            cat_times = m.setdefault("temps_moyen_par_categorie", {})
            cat_hist  = hist["par_categorie"].get(cat, {"total": 0, "succes": 0})
            old_n     = cat_hist["total"]
            if cat in cat_times and cat_times[cat] is not None and old_n > 0:
                cat_times[cat] = round((cat_times[cat] * old_n + res_h) / (old_n + 1), 2)
            else:
                cat_times[cat] = round(res_h, 2)

        # ── Répartition des tickets résolus par priorité (compte tous les tickets
        # résolus, y compris réouverts — même convention que priority_breakdown côté
        # bootstrap Excel, qui compte le total indépendamment du succès) ──
        PRIO_TO_REPARTITION_KEY = {"P1": "P1_critique", "P2": "P2_majeure", "P3": "P3_mineure", "P4": "P4_standard"}
        bk_key = PRIO_TO_REPARTITION_KEY.get(prio)
        if bk_key:
            repartition = m.setdefault(
                "repartition_priorites",
                {"P1_critique": 0, "P2_majeure": 0, "P3_mineure": 0, "P4_standard": 0},
            )
            repartition[bk_key] = repartition.get(bk_key, 0) + 1

        # ── Taux de résolution par priorité ──
        if prio:
            prio_rates = m.setdefault("taux_resolution_par_priorite", {})
            prio_hist  = hist["par_priorite"].setdefault(prio, {"total": 0, "succes": 0})
            old_total  = prio_hist["total"]
            old_succes = prio_hist["succes"]
            new_total  = old_total + 1
            new_succes = old_succes + (1 if success else 0)
            prio_rates[prio]       = round(new_succes / new_total, 3)
            prio_hist["total"]     = new_total
            prio_hist["succes"]    = new_succes

        # ── Historique par catégorie ──
        if cat:
            cat_hist = hist["par_categorie"].setdefault(cat, {"total": 0, "succes": 0})
            cat_hist["total"]  += 1
            if success:
                cat_hist["succes"] += 1

        # ── Auto-découverte de compétences ──
        new_competences = _check_competence_discovery(profile)
        if new_competences:
            profile["competences"] = sorted(set(profile["competences"]) | set(new_competences))

        # ── Recalcul du score de performance ──
        profile["score_performance"] = _recompute_score(profile, profiles)

    return profile


if __name__ == "__main__":
    print("Bootstrap profiling (Python pur, sans LLM)...")
    profiles = run_bootstrap()
    print(f"\n✓ {len(profiles)} profils sauvegardés dans {profiles_store.PROFILES_FILE}\n")
    for p in profiles:
        print(
            f"  {p['nom']:<35} "
            f"score={p['score_performance']:>5}  "
            f"tickets={p['metriques']['total_tickets_historique']:>4}  "
            f"median={p['metriques']['resolution_median_heures']:>6}h  "
            f"compétences={len(p['competences'])}"
        )
