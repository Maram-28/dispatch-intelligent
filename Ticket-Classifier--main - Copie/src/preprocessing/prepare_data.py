"""
Préparation des données d'entraînement depuis les 10 000 tickets LVMH
Génère : dataset de few-shot examples + fichier d'évaluation
"""

import pandas as pd
import json
import random
import re
from pathlib import Path

# ─────────────────────────────────────────────
#  CHARGEMENT ET NETTOYAGE
# ─────────────────────────────────────────────

def _clean_offre(value: str) -> str | None:
    """Nettoie 'NOM DU SERVICE [WW | BU]' -> 'NOM DU SERVICE'."""
    if not isinstance(value, str):
        return None
    v = re.sub(r'\s*\[[^\]]*\]\s*$', '', value).strip()
    return v or None


def load_and_clean(filepath: str) -> pd.DataFrame:
    df = pd.read_excel(filepath)

    # "Offre de services" (catalogue plus granulaire) prime sur "Service"
    # (regroupement macro dans les exports récents) quand elle est renseignée.
    service = None
    if "Offre de services" in df.columns:
        service = df["Offre de services"].apply(_clean_offre)
        if "Service" in df.columns:
            service = service.where(service.notna(), df["Service"])
    elif "Service" in df.columns:
        service = df["Service"]

    # Colonnes clés pour la classification
    key_cols = {
        "Numéro": "numero",
        "Brève description": "breve_description",
        "Description": "description",
        "Catégorie": "categorie",
        "Sous-catégorie": "sous_categorie",
        "Impact": "impact",
        "Urgence": "urgence",
        "Priorité": "priorite",
        "Entreprise": "entreprise",
    }

    df = df[list(key_cols.keys())].rename(columns=key_cols)
    df["service"] = service

    # Nettoyage
    df["breve_description"] = df["breve_description"].astype(str).str.strip()
    df["description"] = df["description"].fillna("").astype(str).str.strip()
    df["description"] = df["description"].str[:3000]  # Tronquer les descriptions longues

    # Filtrer les lignes avec classification complète (gold labels)
    required = ["breve_description", "categorie", "sous_categorie", "service", "impact", "urgence"]
    df_clean = df.dropna(subset=required).copy()
    df_clean = df_clean[df_clean["breve_description"].str.len() > 5]

    print(f"[INFO] Total brut: {len(df)}, après nettoyage: {len(df_clean)}")
    return df_clean


def build_few_shot_examples(df: pd.DataFrame, n: int = 200) -> list[dict]:
    """
    Construit un ensemble d'exemples few-shot représentatifs
    (stratifié par sous-catégorie pour couvrir tous les cas).
    """
    examples = []

    for sous_cat in df["sous_categorie"].unique():
        subset = df[df["sous_categorie"] == sous_cat]
        sample_size = min(n // len(df["sous_categorie"].unique()) + 1, len(subset))
        sample = subset.sample(sample_size, random_state=42)

        for _, row in sample.iterrows():
            examples.append({
                "breve_description": row["breve_description"],
                "description": row["description"][:500],
                "entreprise": row.get("entreprise", ""),
                "labels": {
                    "categorie": row["categorie"],
                    "sous_categorie": row["sous_categorie"],
                    "service": row["service"],
                    "impact": row["impact"],
                    "urgence": row["urgence"],
                    "priorite": row["priorite"],
                }
            })

    random.shuffle(examples)
    return examples[:n]


def build_eval_dataset(df: pd.DataFrame, n: int = 500) -> list[dict]:
    """Ensemble d'évaluation séparé pour mesurer la performance du crew."""
    sample = df.sample(min(n, len(df)), random_state=99)
    eval_data = []
    for _, row in sample.iterrows():
        eval_data.append({
            "numero": row["numero"],
            "breve_description": row["breve_description"],
            "description": row["description"][:500],
            "entreprise": row.get("entreprise", ""),
            "ground_truth": {
                "categorie": row["categorie"],
                "sous_categorie": row["sous_categorie"],
                "service": row["service"],
                "impact": row["impact"],
                "urgence": row["urgence"],
                "priorite": row["priorite"],
            }
        })
    return eval_data


def compute_accuracy(predictions: list[dict], ground_truths: list[dict]) -> dict:
    """Calcule les métriques de performance champ par champ."""
    fields = ["categorie", "sous_categorie", "service", "impact", "urgence"]
    metrics = {f: {"correct": 0, "total": 0} for f in fields}

    for pred, gt in zip(predictions, ground_truths):
        for field in fields:
            metrics[field]["total"] += 1
            if pred.get(field, "").strip() == gt["ground_truth"].get(field, "").strip():
                metrics[field]["correct"] += 1

    return {
        field: {
            "accuracy": round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0,
            "correct": v["correct"],
            "total": v["total"]
        }
        for field, v in metrics.items()
    }


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    input_file = "data/raw/incident-10000.xlsx"
    output_dir = Path("data/processed")
    output_dir.mkdir(exist_ok=True, parents=True)

    print("Chargement des données...")
    df = load_and_clean(input_file)

    print("\nStatistiques des labels :")
    for col in ["categorie", "sous_categorie", "impact", "urgence"]:
        print(f"\n{col}:")
        print(df[col].value_counts().to_string())

    print("\n\nConstruction des few-shot examples (200 exemples stratifiés)...")
    few_shot = build_few_shot_examples(df, n=200)
    with open(output_dir / "few_shot_examples.json", "w", encoding="utf-8") as f:
        json.dump(few_shot, f, ensure_ascii=False, indent=2, default=str)
    print(f"✓ {len(few_shot)} exemples sauvegardés dans data/processed/few_shot_examples.json")

    print("\nConstruction du dataset d'évaluation (500 tickets)...")
    eval_data = build_eval_dataset(df, n=500)
    with open(output_dir / "eval_dataset.json", "w", encoding="utf-8") as f:
        json.dump(eval_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"✓ {len(eval_data)} tickets sauvegardés dans data/processed/eval_dataset.json")

    print("\n✅ Préparation terminée. Prochaine étape: lancer le crew sur eval_dataset.json")
    print("   python evaluate_crew.py")