"""
Script de test SMTP — valide la connexion Gmail et envoie un email de démo.

Usage :
    python tests/test_email.py destinataire@exemple.com

Le script charge les variables depuis .env (SMTP_USERNAME, SMTP_PASSWORD, etc.)
et envoie un email de démo sans dépendre du pipeline de classification.
"""

import sys
import smtplib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Charger .env avant tout import du projet
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
    print("[.env] Variables chargées")
except ImportError:
    print("[.env] python-dotenv non installé — utilisez les variables d'environnement directement")

from src.notifications.email_sender import EmailNotifier


def main():
    if len(sys.argv) < 2:
        print("Usage : python tests/test_email.py destinataire@exemple.com")
        sys.exit(1)

    recipient = sys.argv[1]
    notifier  = EmailNotifier()

    print(f"\n{'─'*50}")
    print(f"  Hôte SMTP    : {notifier.host}:{notifier.port}")
    print(f"  Expéditeur   : {notifier.username}")
    print(f"  Destinataire : {recipient}")
    print(f"  URL plateforme : {notifier.platform_url}")
    print(f"{'─'*50}\n")

    # Test de connexion seule
    print("[1/2] Test de connexion SMTP…")
    try:
        with smtplib.SMTP(notifier.host, notifier.port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(notifier.username, notifier.password)
        print("      ✓ Connexion réussie\n")
    except Exception as exc:
        print(f"      ✗ Échec de connexion : {exc}")
        print("\nVérifiez SMTP_USERNAME et SMTP_PASSWORD dans .env")
        print("Le mot de passe doit être un mot de passe d'application Gmail :")
        print("  Compte Google → Sécurité → Validation en 2 étapes → Mots de passe d'application\n")
        sys.exit(1)

    # Envoi d'un email de démo
    print(f"[2/2] Envoi d'un email de démo à {recipient}…")
    success = notifier.send_assignment(
        recipient_email=recipient,
        recipient_name="Agent Test",
        ticket_numero="INC0099999",
        ticket_titre="Test de notification email",
        ticket_priorite="2-Majeure",
        ticket_sous_categorie="Application",
        ticket_service="O365-PowerBI",
        justification=(
            "Assigné à Agent Test (score : 0.87) : compétences Power BI confirmées "
            "et faible charge actuelle (1 ticket en cours)."
        ),
    )

    if success:
        print(f"      ✓ Email envoyé avec succès à {recipient}")
    else:
        print("      ✗ L'envoi a échoué — consultez les logs ci-dessus")
        sys.exit(1)


if __name__ == "__main__":
    main()
