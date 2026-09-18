#!/usr/bin/env python3
"""
Génère l'exécutable desktop avec PyInstaller — version offline.

Changements par rapport à la version en ligne uniquement :
1. --onedir au lieu de --onefile : nécessaire car l'application embarque
   maintenant un vrai serveur Django (beaucoup de fichiers Python source à
   copier tels quels — erp_project/ — plutôt qu'à figer dans un seul
   binaire). --onefile fonctionnerait aussi mais réextrait tout à chaque
   lancement (démarrage plus lent) ; --onedir démarre instantanément.
2. --hidden-import pour chaque app Django listée dans INSTALLED_APPS :
   PyInstaller analyse le code statiquement et ne voit pas les imports
   dynamiques que fait Django à partir des chaînes de caractères dans
   INSTALLED_APPS — sans cette liste, l'exécutable planterait au premier
   lancement avec "ModuleNotFoundError: No module named 'ventes'", etc.
3. Copie post-build de erp_project/ et erp-frontend/dist/ dans le dossier
   de sortie, à côté de l'exécutable — app.py les cherche à cet endroit
   précis (voir BASE_DIR dans app.py, calculé depuis sys.executable).

IMPORTANT : PyInstaller produit un binaire pour la plateforme sur laquelle
il tourne (pas de cross-compilation). Pour livrer Windows/macOS/Linux, il
faut lancer ce script sur chacun des 3 systèmes (ou une CI GitHub Actions
avec une matrice d'OS).
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

NOM_APP = "ERP-Compta-Logistique"
ICI = Path(__file__).resolve().parent
ERP_PROJECT_SRC = ICI.parent / "erp_project"
FRONTEND_DIST_SRC = ICI.parent / "erp-frontend" / "dist"

# Apps Django (INSTALLED_APPS) + dépendances internes appelées dynamiquement.
# Tenu à jour manuellement — à compléter si une nouvelle app est ajoutée à
# config/settings.py côté erp_project.
HIDDEN_IMPORTS = [
    # Apps métier
    "societes", "utilisateurs", "comptes", "journaux", "logistique",
    "tresorerie", "etats", "notifications", "entreprise", "licences",
    "paie", "demandes", "ventes", "stocks", "synchro",
    # Dépendances Django tierces utilisées via chaînes dans settings.py
    "rest_framework", "rest_framework_simplejwt", "corsheaders",
    "django_filters", "whitenoise", "dj_database_url",
    # Serveur local + synchro
    "waitress", "requests",
    # Génération PDF (paie) — pdf2image n'est PAS listé : vérifié inutilisé
    # dans tout le projet, reportlab suffit et ne dépend d'aucun binaire externe.
    "reportlab", "PIL",
]

DOSSIERS_A_EXCLURE = {"__pycache__", "migrations_backup", ".git"}


def copier_arbre(source, destination):
    if not source.exists():
        print(f"Avertissement : {source} n'existe pas, ignoré (voir README pour le builder d'abord).")
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns(*DOSSIERS_A_EXCLURE, "*.pyc", "db.sqlite3"),
    )
    print(f"Copié : {source} -> {destination}")


def main():
    systeme = platform.system()

    commande = [
        sys.executable, "-m", "PyInstaller",
        "--name", NOM_APP,
        "--onedir",
        "--windowed",
        "--noconfirm",
    ]
    for module in HIDDEN_IMPORTS:
        commande += ["--hidden-import", module]
    commande.append("app.py")

    print(f"Système détecté : {systeme}")
    print("Commande :", " ".join(commande))
    subprocess.run(commande, check=True)

    dossier_sortie = ICI / "dist" / NOM_APP
    copier_arbre(ERP_PROJECT_SRC, dossier_sortie / "erp_project")
    copier_arbre(FRONTEND_DIST_SRC, dossier_sortie / "erp_project" / "frontend_dist")

    print(
        f"\nExécutable généré dans dist/{NOM_APP}/"
        + (f"{NOM_APP}.exe" if systeme == "Windows" else NOM_APP)
        + "\nCe DOSSIER complet (pas juste l'exe) doit être embarqué par l'installateur."
    )


if __name__ == "__main__":
    main()
