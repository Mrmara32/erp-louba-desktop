#!/usr/bin/env python3
"""
Génère l'exécutable desktop avec PyInstaller — version offline.

Changements par rapport à la version en ligne uniquement :
1. --onedir au lieu de --onefile : nécessaire car l'application embarque
   maintenant un vrai serveur Django (beaucoup de fichiers Python source à
   copier tels quels — erp_project/ — plutôt qu'à figer dans un seul
   binaire). --onefile fonctionnerait aussi mais réextrait tout à chaque
   lancement (démarrage plus lent) ; --onedir démarre instantanément.
2. --hidden-import pour chaque app Django listée dans INSTALLED_APPS, ainsi
   que pour tout ce qui est référencé par une CHAÎNE DE CARACTÈRES ailleurs
   dans config/settings.py et config/settings_offline.py (MIDDLEWARE,
   DEFAULT_AUTHENTICATION_CLASSES, DATABASES["ENGINE"], STORAGES, etc.) :
   PyInstaller analyse le code statiquement et ne voit AUCUN de ces imports
   dynamiques — sans cette liste, l'exécutable plante au démarrage avec
   "ModuleNotFoundError: No module named 'ventes'", puis, une fois ça
   corrigé, avec "No module named 'corsheaders.middleware'", etc. — un
   module manquant à la fois. La liste ci-dessous couvre tout ce qui est
   chargé par chaîne de caractères dans les deux fichiers settings actuels ;
   PENSER À LA COMPLÉTER si une nouvelle entrée de ce genre est ajoutée
   (nouvel élément de MIDDLEWARE, nouveau moteur de base de données, etc.).
2bis. --collect-submodules pour les packages tiers dont certains sous-modules
   (ex: rest_framework_simplejwt.views) sont importés depuis le code du
   projet (urls.py, etc.) mais que PyInstaller ne détecte pas non plus
   automatiquement dans ce genre de structure de package. Un simple
   --hidden-import sur le package racine ("rest_framework_simplejwt") ne
   suffit pas à embarquer ses sous-modules ("rest_framework_simplejwt.views") :
   il faut soit lister chaque sous-module utilisé, soit forcer la collecte
   complète du package avec --collect-submodules.
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

# Apps Django (INSTALLED_APPS) + tout module référencé par une chaîne de
# caractères ailleurs dans config/settings.py et config/settings_offline.py.
# Tenu à jour manuellement — à compléter si erp_project/config/settings*.py
# change (nouvelle app, nouveau middleware, nouveau moteur de DB, etc.).
HIDDEN_IMPORTS = [
    # Apps métier
    "societes", "utilisateurs", "comptes", "journaux", "logistique",
    "tresorerie", "etats", "notifications", "entreprise", "licences",
    "paie", "demandes", "ventes", "stocks", "synchro",
    # assistant_ia manquait ici : comme toute app listée dans INSTALLED_APPS,
    # Django l'importe au démarrage (apps.populate()), AVANT que la moindre
    # route ne soit appelée -- son absence ne casse pas que l'assistant,
    # elle empêche l'application ENTIÈRE de démarrer
    # ("ModuleNotFoundError: No module named 'assistant_ia'").
    "assistant_ia",
    # pyotp/qrcode (2FA) : utilisés par utilisateurs/auth_views.py, mêmes
    # symptômes que les autres imports dynamiques de cette liste si absents.
    "pyotp", "qrcode",
    # Fournisseurs d'IA de assistant_ia/views.py : importés dynamiquement
    # (import local dans chaque fonction _repondre_avec_xxx) donc invisibles
    # à l'analyse statique de PyInstaller. google.generativeai n'est volontai-
    # rement PAS ajouté ici : c'est un paquet lourd (dépendances grpc/protobuf)
    # qui pose régulièrement problème avec PyInstaller et qui n'est de toute
    # façon qu'une option parmi trois (voir FOURNISSEURS) -- Groq passe par
    # "requests", déjà embarqué ; seul anthropic (léger) est embarqué ici pour
    # que le mode hors-ligne du poste ait une vraie option IA fonctionnelle
    # dès que GROQ_API_KEY ou ANTHROPIC_API_KEY est configurée côté serveur.
    "anthropic",
    # Dépendances Django tierces utilisées via chaînes dans settings.py
    "rest_framework", "rest_framework_simplejwt", "corsheaders",
    "django_filters", "whitenoise", "dj_database_url",
    # Sous-modules de rest_framework_simplejwt importés directement dans
    # config/urls.py (from rest_framework_simplejwt.views import ...) —
    # non détectés par l'analyse statique de PyInstaller, cause du
    # "ModuleNotFoundError: No module named 'rest_framework_simplejwt.views'"
    # observé en mode hors-ligne.
    "rest_framework_simplejwt.views",
    "rest_framework_simplejwt.serializers",
    "rest_framework_simplejwt.tokens",
    "rest_framework_simplejwt.authentication",
    "rest_framework_simplejwt.exceptions",
    "rest_framework_simplejwt.backends",
    # MIDDLEWARE (config/settings.py) : chaque entrée est importée par
    # Django à partir de son chemin en texte, une par une, au démarrage.
    "django.middleware.security",
    "whitenoise.middleware",
    "corsheaders.middleware",
    "django.contrib.sessions.middleware",
    "django.middleware.common",
    "django.middleware.csrf",
    "django.contrib.auth.middleware",
    "django.contrib.messages.middleware",
    "django.middleware.clickjacking",
    # REST_FRAMEWORK : classes référencées par chaîne (authentification,
    # permission par défaut, pagination).
    "licences.authentication",
    "rest_framework.permissions",
    "rest_framework.pagination",
    # AUTH_PASSWORD_VALIDATORS (chaînes également).
    "django.contrib.auth.password_validation",
    # STORAGES["staticfiles"]["BACKEND"].
    "whitenoise.storage",
    # DATABASES["ENGINE"] : sqlite3 est utilisé par config/settings_offline.py
    # (mode hors-ligne, le cas justement le plus important à ne pas casser).
    "django.db.backends.sqlite3",
    # EMAIL_BACKEND (settings.py par défaut + settings_offline.py).
    "django.core.mail.backends.console",
    "django.core.mail.backends.locmem",
    # Serveur local + synchro
    "waitress", "requests",
    # Génération PDF (paie) — pdf2image n'est PAS listé : vérifié inutilisé
    # dans tout le projet, reportlab suffit et ne dépend d'aucun binaire externe.
    "reportlab", "PIL",
]

# Packages dont TOUS les sous-modules doivent être embarqués (au-delà des
# entrées listées explicitement ci-dessus), pour éviter de devoir ajouter
# un "ModuleNotFoundError" à la fois à chaque nouvelle route DRF/JWT/CORS
# utilisée dans le projet.
COLLECT_SUBMODULES = [
    "rest_framework_simplejwt",
    "rest_framework",
    "corsheaders",
    "django_filters",
    # "reportlab.lib" (utilisé dans paie/pdf.py pour générer les bulletins de
    # paie en PDF) n'est pas détecté par l'analyse statique de PyInstaller —
    # même symptôme que rest_framework_simplejwt : "ModuleNotFoundError:
    # No module named 'reportlab.lib'" à l'exécution en mode hors-ligne.
    "reportlab",
    # PIL est utilisé par reportlab pour l'insertion d'images dans les PDF ;
    # collecté par précaution pour le même genre de sous-import dynamique.
    "PIL",
    # openpyxl (export Excel des releves de compte) a le meme genre de
    # sous-imports dynamiques que reportlab/PIL ci-dessus.
    "openpyxl",
    # qrcode (QR code du secret 2FA) a le meme genre de sous-imports
    # dynamiques (qrcode.image.pil, etc.) que les paquets ci-dessus.
    "qrcode",
    # anthropic (Assistant IA) : paquet avec de nombreux sous-modules
    # (anthropic.types, anthropic._client, ...) importés dynamiquement par
    # le SDK lui-même, non détectés par l'analyse statique de PyInstaller.
    "anthropic",
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
        #"--windowed",
        "--noconfirm",
    ]
    for module in HIDDEN_IMPORTS:
        commande += ["--hidden-import", module]
    for package in COLLECT_SUBMODULES:
        commande += ["--collect-submodules", package]
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
