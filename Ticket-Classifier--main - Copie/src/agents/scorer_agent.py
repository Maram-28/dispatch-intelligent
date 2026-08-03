"""
LVMH Power BI Ticket Dispatch
EY Data Team - Module 2 Part 2: Scorer Agent (CrewAI)

Responsabilités :
  - Filtrer les membres indisponibles (filtre dur)
  - Scorer les membres disponibles via formule multi-critères
  - Générer une justification en français via LLM
  - Retourner l'assignation finale

Formule :
  score = match_competence × 0.35 + brand_affinity × 0.25
        + (1 - charge_norm) × 0.25 + performance_norm × 0.15

  match_competence = (score_sous_cat + score_service) / 2
    score_sous_cat  = skills_trouvés / skills_requis  (graduel)
    score_service   = 1.0 si skill du service présent, sinon 0.0
  brand_affinity  = services_marque_matchés / total_services_membre
"""

import json
import os
from typing import Optional, Type, Any

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, ConfigDict

from src.agents.profiling_agent import (
    get_profiles_for_scorer,
    SOUS_CAT_TO_SKILLS,
    SERVICE_KEYWORD_TO_SKILL,
)


# ─────────────────────────────────────────────
#  LLM HELPER — Azure OpenAI EY Gateway
# ─────────────────────────────────────────────

def _build_llm(model_override: str = None) -> LLM:
    """
    Construit le LLM pour le gateway Azure APIM EY.
    URL : {base_url}/openai/deployments/{deployment}/chat/completions
    Auth : header api-key (format Azure APIM).
    """
    deployment  = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o")
    api_key     = os.environ.get("OPENAI_API_KEY", "")
    base_url    = (os.environ.get("OPENAI_ENDPOINT") or os.environ.get("OPENAI_API_BASE", "")).rstrip("/")

    azure_base = f"{base_url}/openai/deployments/{deployment}"

    return LLM(
        model=f"openai/{deployment}",
        api_key=api_key,
        base_url=azure_base,
        extra_headers={"api-key": api_key},
    )


# ─────────────────────────────────────────────
#  HELPERS DE SCORING (Python pur, déterministe)
# ─────────────────────────────────────────────

def _match_competence(profile: dict, sous_categorie: str, service: str) -> float:
    competences = set(profile.get("competences", []))

    required = SOUS_CAT_TO_SKILLS.get(sous_categorie, [])
    score_sous_cat = (
        sum(1 for s in required if s in competences) / len(required)
        if required else 0.5
    )

    service_lower = service.lower()
    score_service = 0.0
    for keyword, skill in SERVICE_KEYWORD_TO_SKILL.items():
        if keyword in service_lower and skill in competences:
            score_service = 1.0
            break

    return (score_sous_cat + score_service) / 2


def _brand_affinity(profile: dict, entreprise: str) -> float:
    if not entreprise:
        return 0.5

    top_services = profile.get("specialisations", {}).get("services", [])
    if not top_services:
        return 0.0

    ent_lower = entreprise.lower()
    matching = sum(1 for svc in top_services if ent_lower in svc.lower())
    return matching / len(top_services)


def _score_member(
    profile: dict,
    sous_categorie: str,
    service: str,
    entreprise: str,
    max_perf: float,
) -> dict:
    mc = _match_competence(profile, sous_categorie, service)
    ba = _brand_affinity(profile, entreprise)
    ch = 1.0 - profile.get("charge_normalisee", 0.0)
    pf = profile.get("score_performance", 0) / max_perf if max_perf > 0 else 0.0

    total = mc * 0.35 + ba * 0.25 + ch * 0.25 + pf * 0.15

    return {
        "membre_id": profile["id"],
        "nom": profile["nom"],
        "score": round(total, 4),
        "details": {
            "match_competence": round(mc, 3),
            "brand_affinity": round(ba, 3),
            "charge_inverse": round(ch, 3),
            "performance_norm": round(pf, 3),
            "charge_actuelle": profile.get("charge_actuelle", 0),
            "competences_matchees": [
                s for s in SOUS_CAT_TO_SKILLS.get(sous_categorie, [])
                if s in set(profile.get("competences", []))
            ],
            "services_marque": [
                svc for svc in profile.get("specialisations", {}).get("services", [])
                if entreprise.lower() in svc.lower()
            ] if entreprise else [],
        },
    }


# ─────────────────────────────────────────────
#  TOOL SCHEMA + TOOL
# ─────────────────────────────────────────────

class ScoreMembersInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_sous_categorie: str = Field(..., description="Sous-catégorie ITIL du ticket.")
    ticket_service: str = Field(..., description="Service Power BI concerné.")
    ticket_entreprise: str = Field(default="", description="Entreprise/maison LVMH émettrice.")


class ScoreMembersDispatchTool(BaseTool):
    name: str = "score_members_dispatch"
    description: str = (
        "Calcule le score de dispatch de chaque membre disponible pour un ticket IT. "
        "Applique un filtre dur sur la disponibilité (absent = exclu). "
        "Retourne un classement JSON trié par score décroissant."
    )
    args_schema: Type[BaseModel] = ScoreMembersInput

    def _run(
        self,
        ticket_sous_categorie: str,
        ticket_service: str,
        ticket_entreprise: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            profiles = get_profiles_for_scorer()
        except FileNotFoundError:
            return json.dumps({"error": "profiles_not_found", "rankings": []})

        available = [p for p in profiles if p.get("disponible", True)]
        if not available:
            return json.dumps({
                "error": "no_assignee_available",
                "message": "Aucun membre disponible pour l'assignation.",
                "rankings": [],
            })

        max_perf = max(p.get("score_performance", 0) for p in available) or 1.0
        rankings = [
            _score_member(p, ticket_sous_categorie, ticket_service, ticket_entreprise, max_perf)
            for p in available
        ]
        rankings.sort(key=lambda x: x["score"], reverse=True)
        return json.dumps({"rankings": rankings}, ensure_ascii=False)


# ─────────────────────────────────────────────
#  OUTPUT SCHEMA
# ─────────────────────────────────────────────

class AssignmentOutput(BaseModel):
    membre_id: str
    nom: str
    score_assignation: float
    justification: str


# ─────────────────────────────────────────────
#  CREW ENTRY POINT
# ─────────────────────────────────────────────

def assign_ticket(
    ticket_entreprise: str,
    ticket_sous_categorie: str,
    ticket_service: str,
    ticket_numero: str,
    llm_model: str = None,
) -> Optional[AssignmentOutput]:
    """
    Lance le Scorer Agent CrewAI pour assigner le ticket au meilleur membre disponible.
    Retourne None si les profils n'existent pas ou si une erreur survient.
    """
    tool = ScoreMembersDispatchTool()
    llm = _build_llm(llm_model)

    dispatch_agent = Agent(
        role="Responsable Dispatch IT LVMH",
        goal="Assigner chaque ticket IT au membre de l'équipe le mieux adapté.",
        backstory=(
            "Expert en gestion d'incidents IT pour l'équipe Power BI LVMH EY. "
            "Tu utilises l'outil score_members_dispatch pour identifier le meilleur candidat "
            "parmi les membres disponibles, puis tu fournis une justification concise en français."
        ),
        tools=[tool],
        llm=llm,
        verbose=True,
    )

    task_dispatch = Task(
        description=f"""
Assigne le ticket {ticket_numero} au membre de l'équipe le plus adapté.

Informations du ticket :
- Entreprise : {ticket_entreprise or 'Non spécifiée'}
- Sous-catégorie : {ticket_sous_categorie}
- Service : {ticket_service}

Étape 1 : Appelle l'outil score_members_dispatch avec :
  ticket_sous_categorie = "{ticket_sous_categorie}"
  ticket_service = "{ticket_service}"
  ticket_entreprise = "{ticket_entreprise or ''}"

Étape 2 : Prends le membre avec le score le plus élevé dans rankings[0].
Si rankings est vide (aucun membre disponible), utilise :
  membre_id = "no_assignee", nom = "Aucun membre disponible", score_assignation = 0.0

Étape 3 : Génère une justification concise en français (1 phrase) expliquant pourquoi
ce membre est le meilleur choix (compétences, affinité marque, charge, performance).
""",
        expected_output="""JSON strictement dans ce format (aucun autre texte) :
{{
  "membre_id": "id_du_membre",
  "nom": "Prénom NOM",
  "score_assignation": 0.00,
  "justification": "Assigné à Prénom NOM (score : 0.XX) : raison principale."
}}""",
        agent=dispatch_agent,
        output_pydantic=AssignmentOutput,
    )

    crew = Crew(
        agents=[dispatch_agent],
        tasks=[task_dispatch],
        process=Process.sequential,
        verbose=True,
    )

    try:
        result = crew.kickoff()
        return result.pydantic
    except Exception as e:
        print(f"[SCORER] Erreur CrewAI : {e}")
        return None
