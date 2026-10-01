#!/usr/bin/env python3
"""
Genere la variante "100% offline" de l'executable desktop : jamais de
bascule automatique en ligne, jamais de synchronisation en arriere-plan.
L'utilisateur peut tout de meme ouvrir une connexion en ligne a la demande
(menu Aide -> "Se connecter en ligne"), mais rien ne se passe tout seul.

Reprend exactement la meme logique que build.py (memes hidden-imports, meme
copie de erp_project/ et erp-frontend/dist/) -- seule difference : le nom de
l'executable, et un config.json ecrit dans le dossier de sortie avec
"type_installation": "offline_pur" (voir erp-desktop/app.py::main()).

Necessite que patch16.py ait deja ete applique a erp-desktop/app.py (la
branche "offline_pur" doit exister dans main()).

Usage :
    python build_offline_pur.py
"""
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

NOM_APP = "ERP-Compta-Logistique-OfflinePur"
ICI = Path(__file__).resolve().parent
ERP_PROJECT_SRC = ICI.parent / "erp_project"
FRONTEND_DIST_SRC = ICI.parent / "erp-frontend" / "dist"

HIDDEN_IMPORTS = [
    "societes", "utilisateurs", "comptes", "journaux", "logistique",
    "tresorerie", "etats", "notifications", "entreprise", "licences",
    "paie", "demandes", "ventes", "stocks", "synchro",
    "rest_framework", "rest_framework_simplejwt", "corsheaders",
    "django_filters", "whitenoise", "dj_database_url",
    "rest_framework_simplejwt.views",
    "rest_framework_simplejwt.serializers",
    "rest_framework_simplejwt.tokens",
    "rest_framework_simplejwt.authentication",
    "rest_framework_simplejwt.exceptions",
    "rest_framework_simplejwt.backends",
    "django.middleware.security",
    "whitenoise.middleware",
    "corsheaders.middleware",
    "django.contrib.sessions.middleware",
    "django.middleware.common",
    "django.middleware.csrf",
    "django.contrib.auth.middleware",
    "django.contrib.messages.middleware",
    "django.middleware.clickjacking",
    "licences.authentication",
    "rest_framework.permissions",
    "rest_framework.pagination",
    "django.contrib.auth.password_validation",
    "whitenoise.storage",
    "django.db.backends.sqlite3",
    "django.core.mail.backends.console",
    "django.core.mail.backends.locmem",
    "waitress", "requests",
    "reportlab", "PIL",
]

COLLECT_SUBMODULES = [
    "rest_framework_simplejwt",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "reportlab",
    "PIL",
    "openpyxl",
]

DOSSIERS_A_EXCLURE = {"__pycache__", "migrations_backup", ".git"}

CONFIG_OFFLINE_PUR = {
    "type_installation": "offline_pur",
}


def copier_arbre(source, destination):
    if not source.exists():
        print(f"Avertissement : {source} n'existe pas, ignore (voir README pour le builder d'abord).")
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns(*DOSSIERS_A_EXCLURE, "*.pyc", "db.sqlite3"),
    )
    print(f"Copie : {source} -> {destination}")


def main():
    systeme = platform.system()

    commande = [
        sys.executable, "-m", "PyInstaller",
        "--name", NOM_APP,
        "--onedir",
        "--noconfirm",
    ]
    for module in HIDDEN_IMPORTS:
        commande += ["--hidden-import", module]
    for package in COLLECT_SUBMODULES:
        commande += ["--collect-submodules", package]
    commande.append("app.py")

    print(f"Systeme detecte : {systeme}")
    print("Commande :", " ".join(commande))
    subprocess.run(commande, check=True)

    dossier_sortie = ICI / "dist" / NOM_APP
    copier_arbre(ERP_PROJECT_SRC, dossier_sortie / "erp_project")
    copier_arbre(FRONTEND_DIST_SRC, dossier_sortie / "erp_project" / "frontend_dist")

    with open(dossier_sortie / "config.json", "w", encoding="utf-8") as f:
        json.dump(CONFIG_OFFLINE_PUR, f, indent=2, ensure_ascii=False)
    print(f"config.json (offline_pur) ecrit dans {dossier_sortie}")

    print(
        f"\nExecutable genere dans dist/{NOM_APP}/"
        + (f"{NOM_APP}.exe" if systeme == "Windows" else NOM_APP)
        + "\nCe DOSSIER complet (pas juste l'exe) doit etre embarque par l'installateur."
        + "\nDemarre toujours en local, sans aucune tentative reseau automatique."
    )


if __name__ == "__main__":
    main()
