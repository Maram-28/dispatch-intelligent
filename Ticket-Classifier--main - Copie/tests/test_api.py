"""
Script de test rapide - Mode standalone, sans ServiceNow ni OpenAI.
Lance l'API et classifie un extrait de tes tickets depuis le fichier Excel.
"""

import pandas as pd
import requests
import json
import time
import sys
from pathlib import Path

API_URL = "http://localhost:8000"


def test_health():
    print("1️⃣  Test de santé de l'API...")
    r = requests.get(f"{API_URL}/health")
    print(f"   ✅ {r.json()}\n")


def test_single_ticket():
    print("2️⃣  Test ticket unique...")
    ticket = {
        "numero": "INC_TEST_001",
        "breve_description": "Données manquantes dans le dashboard retail scorecard",
        "description": "Depuis ce matin, les données de ventes de la semaine dernière n'apparaissent pas dans le rapport.",
        "entreprise": "DIOR"
    }
    r = requests.post(f"{API_URL}/classify", json=ticket)
    result = r.json()
    print(f"   Ticket : {ticket['breve_description']}")
    print(f"   ✅ Catégorie     : {result['categorie']}")
    print(f"   ✅ Sous-catégorie: {result['sous_categorie']}")
    print(f"   ✅ Service       : {result['service']}")
    print(f"   ✅ Impact        : {result['impact']}")
    print(f"   ✅ Urgence       : {result['urgence']}")
    print(f"   ✅ Priorité      : {result['priorite_calculee']}")
    print(f"   🔍 Confiance     : {result['confidence']}")
    print(f"   💬 Raisonnement  : {result['reasoning']}\n")


def test_batch():
    print("3️⃣  Test batch (5 tickets variés)...")
    tickets = [
        {"numero": "INC001", "breve_description": "Accès Power BI refusé", "entreprise": "GUERLAIN"},
        {"numero": "INC002", "breve_description": "[TechTicketing] [DailyCheck] AAS - KO Job - PCD-CRM", "entreprise": "DIOR"},
        {"numero": "INC003", "breve_description": "Dashboard publication KO - erreur gateway", "entreprise": "SSC"},
        {"numero": "INC004", "breve_description": "Données de ventes erronées dans le rapport", "entreprise": "LVMH BEAUTY TECH"},
        {"numero": "INC005", "breve_description": "Demande d'évolution : ajouter filtre par région", "entreprise": "MAKE UP FOR EVER"},
    ]
    r = requests.post(f"{API_URL}/classify/batch", json=tickets)
    data = r.json()
    print(f"   {data['classified']}/{data['total']} tickets classifiés\n")
    for res in data["results"]:
        print(f"   [{res['numero']}] {res['categorie']} | {res['sous_categorie']} | {res['service'][:30]} | {res['impact']} | {res['urgence']}")
    print()


def test_excel_upload(filepath: str = None):
    print("4️⃣  Test upload Excel...")

    if not filepath:
        # Créer un mini fichier de test
        test_data = pd.DataFrame([
            {"Numéro": "INC_A001", "Brève description": "Accès refusé rapport ventes", "Entreprise": "DIOR"},
            {"Numéro": "INC_A002", "Brève description": "Données refresh KO ce matin", "Entreprise": "GUERLAIN"},
            {"Numéro": "INC_A003", "Brève description": "[TechTicketing] [DailyCheck] AAS KO", "Entreprise": "DIOR"},
            {"Numéro": "INC_A004", "Brève description": "Publication dashboard impossible", "Entreprise": "SSC"},
            {"Numéro": "INC_A005", "Brève description": "Demande nouveau rapport mensuel", "Entreprise": "MAKE UP FOR EVER"},
        ])
        test_file = Path("data/raw/test_tickets_mini.xlsx")
        test_data.to_excel(test_file, index=False)
        filepath = str(test_file)
        print(f"   📄 Fichier de test créé : {filepath}")
    else:
        print(f"   📄 Fichier : {filepath}")

    with open(filepath, "rb") as f:
        r = requests.post(f"{API_URL}/classify/upload", files={"file": (Path(filepath).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    job = r.json()
    job_id = job["job_id"]
    print(f"   Job créé : {job_id}")

    # Attendre la fin du job
    for _ in range(30):
        time.sleep(0.5)
        status = requests.get(f"{API_URL}/jobs/{job_id}").json()
        print(f"   ⏳ {status['status']} ({status['processed']}/{status['total']})", end="\r")
        if status["status"] in ("done", "error"):
            break

    print(f"\n   ✅ Job terminé : {status['status']}")

    if status["status"] == "done":
        # Télécharger le résultat
        output = requests.get(f"{API_URL}/jobs/{job_id}/download")
        output_path = Path(f"data/output/results_{job_id}.xlsx")
        output_path.parent.mkdir(exist_ok=True, parents=True)
        with open(output_path, "wb") as f:
            f.write(output.content)
        print(f"   📥 Résultats téléchargés : {output_path}")

        # Afficher un aperçu
        df = pd.read_excel(output_path, sheet_name="Classifications")
        print(f"\n   Aperçu des résultats :")
        print(df[["numero", "categorie", "sous_categorie", "service", "impact", "urgence", "priorite_calculee"]].to_string(index=False))
    print()


def test_manual_correction(job_id: str = None):
    if not job_id:
        return
    print("5️⃣  Test correction manuelle...")
    correction = {
        "numero": "INC_A001",
        "job_id": job_id,
        "service": "PCD - Retail Scorecard",
        "correction_note": "Service corrigé manuellement par l'analyste"
    }
    r = requests.patch(f"{API_URL}/jobs/{job_id}/correct", json=correction)
    print(f"   ✅ {r.json()}\n")


if __name__ == "__main__":
    # Usage : python test_api.py [chemin_vers_excel]
    excel_path = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        test_health()
        test_single_ticket()
        test_batch()
        test_excel_upload(excel_path)
        print("✅ Tous les tests passés avec succès !")
    except requests.exceptions.ConnectionError:
        print("❌ L'API n'est pas démarrée. Lance d'abord : python api.py")