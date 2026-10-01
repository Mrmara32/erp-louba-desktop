"""
Coquille desktop de l'ERP Compta & Logistique — version avec mode offline
ET mode réseau local (bureau partagé sans internet).

Trois modes possibles, testés dans cet ordre à chaque démarrage :

1. CLIENT RÉSEAU LOCAL : si config["serveur_local_url"] est renseignée et
   qu'un collègue a déjà démarré son poste en mode SERVEUR LOCAL sur le
   même réseau (WiFi/Ethernet du bureau), ce poste s'y connecte directement
   comme client léger — aucune base locale, aucune synchro différée : on
   travaille en temps réel sur LA MÊME base que le collègue serveur.

2. EN LIGNE : si internet est disponible (et qu'aucun serveur local n'a
   répondu), connexion directe à Render, comme aujourd'hui.

3. ISOLÉ (ou SERVEUR LOCAL) : sinon, démarre un serveur Django local sur
   une base SQLite locale. Si config["role_reseau"] == "serveur_local",
   ce serveur écoute sur TOUTES les interfaces réseau (0.0.0.0) pour que
   d'autres postes du bureau puissent s'y connecter en mode 1 — sinon il
   n'écoute que localement (isolé, synchronisation différée par internet
   via sync_worker.py quand la connexion revient).

Configuration : voir config.json. Champs pertinents pour le mode réseau
local :
  "role_reseau"       : "auto" (défaut) | "serveur_local" | "isole"
  "serveur_local_url" : ex "http://192.168.1.42:8813" — adresse du poste
                        collègue à essayer en priorité si configuré en
                        serveur_local ce jour-là. Laisser vide si sans objet.

ATTENTION SÉCURITÉ : le mode serveur_local écoute sur tout le réseau local
(0.0.0.0) — à n'utiliser que sur un réseau de confiance (bureau, domicile),
jamais sur un WiFi public, et jamais avec le port ouvert vers internet
(pas de redirection de port sur la box/routeur).

CORRECTIF CONNEXION AUTOMATIQUE HORS LIGNE (voir _url_avec_token ci-dessous) :
Avant ce correctif, le token sauvegardé lors d'une connexion en ligne était
réinjecté dans la page APRÈS son chargement complet (sur l'événement pywebview
"loaded", via window.evaluate_js). Le problème : React (AuthContext) lit déjà
localStorage et décide qu'aucun utilisateur n'est connecté AVANT que cette
injection tardive n'ait lieu — donc la page de connexion s'affichait à chaque
fois en mode hors ligne, même après une connexion en ligne réussie suivie
d'une déconnexion internet propre. Le token est maintenant transmis dans
l'URL de la fenêtre (paramètres de requête) DÈS SA CRÉATION, et
erp-frontend/src/main.jsx le récupère et l'écrit dans localStorage AVANT le
tout premier rendu de React — donc avant qu'AuthContext ne le lise.

CORRECTIF N°2 — LA VRAIE CAUSE DES DONNÉES VIDES HORS LIGNE :
Le registre de synchronisation (erp_project/synchro/registry.py::REFERENTIEL)
prévoit bien de rapatrier utilisateurs.Utilisateur, licences.Licence,
comptes.Tiers, comptes.CompteComptable, etc. vers la base locale PENDANT que
le poste est en ligne (sync_worker.py, toutes les 60s), pour que tout soit
déjà là au moment de basculer hors ligne. Mais ce mécanisme ne pouvait
JAMAIS fonctionner : le serveur Django local (127.0.0.1:8813), qui est la
DESTINATION de cette synchro, n'était démarré qu'en Mode 3 (hors ligne) —
jamais en Mode 2 (en ligne). Le worker de synchro tournait donc dans le
vide : ses requêtes vers 127.0.0.1:8813 échouaient silencieusement (personne
n'écoutait), la base locale restait perpétuellement vide, et donc :
  - aucun utilisateur local -> le token, même bien injecté, était rejeté
    (401) dès qu'une requête locale tentait de l'authentifier ;
  - aucun Tiers / CompteComptable -> pages bloquées sur "Chargement..." une
    fois hors ligne, puisqu'il n'y avait tout simplement rien à charger.
Le Mode 2 démarre maintenant, lui aussi, le serveur Django local en tâche de
fond (invisible : la fenêtre affichée continue de pointer vers Render) —
juste pour que la synchro ait enfin un endroit où écrire pendant que vous
travaillez en ligne.

CORRECTIF N°3 — SECRET_KEY PARTAGÉE :
Un token JWT n'est valide que si sa signature est vérifiée avec la MÊME
DJANGO_SECRET_KEY que celle qui l'a émis. Le token est émis par Render (en
ligne) ; il doit donc être vérifiable avec la même clé une fois rejoué
contre le serveur Django local. SECRET_KEY_PARTAGEE ci-dessous DOIT être
recopiée à l'identique dans la variable d'environnement DJANGO_SECRET_KEY du
service Render (Dashboard Render -> service backend -> Environment).
"""
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import urlencode, urlparse
import webview

if sys.platform.startswith("linux") and os.geteuid() == 0:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DJANGO_LOCAL_PORT = 8813
DJANGO_LOCAL_URL = f"http://127.0.0.1:{DJANGO_LOCAL_PORT}"

# DOIT être IDENTIQUE à la variable d'environnement DJANGO_SECRET_KEY du
# service Render (voir note en tête de fichier, correctif n°3). Sans ça, un
# token émis en ligne ne peut jamais être validé par le serveur Django
# local, même une fois correctement transmis et même une fois l'utilisateur
# correctement synchronisé dans la base locale.
SECRET_KEY_PARTAGEE = "k8x!Qz3mP9vR2wL7nB5tY4cJ6hF1sD0aE8gU3iO7pV2xM9qN"

DEFAULT_CONFIG = {
    "url": "https://erp-louba-frontend.onrender.com",
    "serveur_backend": "https://erp-louba-backend.onrender.com",
    "title": "ERP Comptabilité & Logistique",
    "width": 1400,
    "height": 900,
    "min_width": 1024,
    "min_height": 700,
    "device_id": None,
    "role_reseau": "auto",       # "auto" | "serveur_local" | "isole"
    "serveur_local_url": "",     # ex: "http://192.168.1.42:8813"
    # "complete" (défaut) : bascule automatique en ligne/hors-ligne + synchro
    # en tâche de fond (comportement historique, voir main()).
    # "offline_pur" : ne tente JAMAIS automatiquement une connexion internet
    # ni de synchronisation en arrière-plan -- démarre toujours directement
    # en local. Un bouton "Se connecter en ligne" (menu Aide, voir
    # MenuBar.jsx) ouvre une fenêtre séparée vers Render UNIQUEMENT quand
    # l'utilisateur le demande explicitement ; aucune synchro automatique
    # n'a lieu même après cette connexion manuelle. Voir build_offline_pur.py.
    "type_installation": "complete",   # "complete" | "offline_pur"
}

_compteur_fenetres = 0


def charger_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Avertissement : config.json illisible ({e}), utilisation des valeurs par défaut.")
    if os.environ.get("ERP_URL"):
        config["url"] = os.environ["ERP_URL"]
    return config


def _device_id(config):
    if config.get("device_id"):
        return config["device_id"]
    return f"{socket.gethostname()}-{os.name}"


def adresse_joignable(url, timeout=2):
    """Test générique : le serveur derrière cette URL répond-il ? Utilisé
    aussi bien pour tester internet (Render) que le serveur local du bureau."""
    try:
        hote = urlparse(url).hostname
        port = urlparse(url).port or (443 if url.startswith("https") else 80)
        socket.create_connection((hote, port), timeout=timeout)
        return True
    except (OSError, ValueError):
        return False


def internet_disponible(hote_url, timeout=3):
    return adresse_joignable(hote_url, timeout=timeout)


def obtenir_ip_locale():
    """
    Astuce classique pour obtenir l'adresse IP de la machine SUR LE RÉSEAU
    LOCAL (pas 127.0.0.1) sans dépendance externe : ouvre une connexion UDP
    (aucune donnée réellement envoyée) vers une adresse publique, puis lit
    l'adresse locale que le système a choisie pour cette route.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _chemin_token():
    nom_app = "LoubaERP"
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        dossier = os.path.join(base, nom_app)
    elif sys.platform == "darwin":
        dossier = os.path.join(os.path.expanduser("~"), "Library", "Application Support", nom_app)
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
        dossier = os.path.join(base, nom_app)
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, "token.json")
    os.environ["ERP_TOKEN_PATH"] = chemin
    return chemin


def _charger_token_local():
    chemin = _chemin_token()
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def demarrer_django_local(host="127.0.0.1"):
    """
    Lance le backend Django en mode offline (settings_offline) via waitress.
    host="0.0.0.0" en mode serveur_local pour accepter les connexions des
    autres postes du bureau ; host="127.0.0.1" en mode isolé (personne
    d'autre ne doit pouvoir s'y connecter).
    """
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_offline"
    # Voir correctif n°3 en tête de fichier : doit matcher DJANGO_SECRET_KEY
    # sur Render pour que les tokens émis en ligne restent valides ici.
    # setdefault (et non affectation directe) : si un opérateur a
    # explicitement défini DJANGO_SECRET_KEY dans l'environnement du poste
    # (cas avancé), on respecte ce choix plutôt que de l'écraser.
    os.environ.setdefault("DJANGO_SECRET_KEY", SECRET_KEY_PARTAGEE)
    if host == "0.0.0.0":
        # Nécessaire pour que Django accepte les requêtes venant d'autres
        # machines du réseau (sinon DisallowedHost) — sûr uniquement parce
        # que ce serveur n'écoute que sur le réseau local, jamais exposé à
        # internet (voir avertissement sécurité en haut de ce fichier).
        os.environ["ERP_ALLOWED_HOSTS_SUPPLEMENTAIRES"] = "*"

    erp_project_dir = os.path.join(BASE_DIR, "erp_project")
    sys.path.insert(0, erp_project_dir)

    import django
    django.setup()

    from django.core.management import call_command
    print("[offline] Vérification / création de la base locale...")
    call_command("migrate", interactive=False, verbosity=0)
    print("[offline] Base locale prête.")

    from waitress import serve
    from config.wsgi import application

    def _run():
        serve(application, host=host, port=DJANGO_LOCAL_PORT)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", DJANGO_LOCAL_PORT), timeout=0.5)
            break
        except OSError:
            time.sleep(0.2)


class Api:
    def __init__(self, config):
        self.config = config

    def nouvelle_fenetre(self):
        global _compteur_fenetres
        _compteur_fenetres += 1
        titre = f"{self.config['title']} — Fenêtre {_compteur_fenetres + 1}"
        creer_fenetre(self.config, titre)
        return True

    def enregistrer_token(self, access=None, refresh=None):
        donnees = _charger_token_local() or {}
        if access:
            donnees["access"] = access
        if refresh:
            donnees["refresh"] = refresh
        with open(_chemin_token(), "w", encoding="utf-8") as f:
            json.dump(donnees, f)
        return True

    def connecter_en_ligne(self):
        """
        Appelé depuis le frontend (menu Aide -> "Se connecter en ligne"),
        pensé pour le mode offline_pur : ouvre une fenêtre séparée pointant
        vers Render, à la demande explicite de l'utilisateur. Ne démarre
        jamais de synchro automatique -- l'utilisateur travaille ensuite
        normalement dans cette fenêtre en ligne (ex: gérer sa licence), qui
        se ferme simplement quand il a terminé.
        """
        if not internet_disponible(self.config["serveur_backend"]):
            return {"ok": False, "detail": "Aucune connexion internet détectée."}
        titre = f"{self.config['title']} — En ligne"
        creer_fenetre(self.config, titre, url=self.config["url"])
        return {"ok": True}

    def synchroniser_maintenant(self):
        """
        Appelé depuis le frontend (menu Aide -> "Synchroniser maintenant").
        Déclenche UNE SEULE synchronisation (push des documents en attente +
        pull du référentiel -- utilisateurs, tiers, comptes, licence...) avec
        Render, puis s'arrête : pas de boucle, pas de répétition automatique
        (voir sync_worker.synchroniser_une_fois, utilisé aussi par la boucle
        du mode "complete"). C'est le seul moyen, en mode offline_pur, de
        faire apparaître un compte/des données dans la base locale -- à
        utiliser au moins une fois après "Se connecter en ligne", avant de
        pouvoir se connecter localement en étant totalement hors-ligne.
        """
        if not internet_disponible(self.config["serveur_backend"]):
            return {"ok": False, "detail": "Aucune connexion internet détectée."}
        from sync_worker import synchroniser_une_fois
        try:
            synchroniser_une_fois(
                self.config["serveur_backend"], DJANGO_LOCAL_URL, _device_id(self.config)
            )
        except Exception as e:
            return {"ok": False, "detail": f"Échec de la synchronisation : {e}"}
        return {"ok": True}


def creer_fenetre(config, titre=None, url=None):
    return webview.create_window(
        title=titre or config["title"],
        url=url or config["url"],
        width=config["width"],
        height=config["height"],
        min_size=(config["min_width"], config["min_height"]),
        text_select=True,
        resizable=True,
        js_api=Api(config),
    )


def _url_avec_token(url_base, token):
    """
    Ajoute le token sauvegardé (s'il existe) comme paramètres de requête sur
    l'URL de la fenêtre, AVANT sa création — donc avant que la moindre ligne
    de JavaScript ne s'exécute. erp-frontend/src/main.jsx lit ces paramètres
    et les copie dans localStorage avant le premier rendu de React, ce qui
    évite la course avec AuthContext (voir note en tête de fichier).

    Remplace l'ancienne approche (_injecter_token_dans_page / evaluate_js sur
    l'événement "loaded"), qui arrivait toujours trop tard.
    """
    if not token or not token.get("access"):
        return url_base
    parametres = {"access_token": token["access"]}
    if token.get("refresh"):
        parametres["refresh_token"] = token["refresh"]
    separateur = "&" if "?" in url_base else "?"
    return f"{url_base}{separateur}{urlencode(parametres)}"


def main():
    config = charger_config()
    type_installation = config.get("type_installation", "complete")

    # --- Mode OFFLINE PUR : jamais de bascule/synchro automatique --------
    # Build séparée (voir build_offline_pur.py) pour les postes qui doivent
    # rester strictement locaux au quotidien : pas de détection internet au
    # démarrage, pas de serveur local partagé entre collègues, pas de
    # sync_worker. L'utilisateur peut tout de même ouvrir une connexion en
    # ligne À LA DEMANDE (Api.connecter_en_ligne, déclenché depuis le menu
    # Aide du frontend) -- mais rien n'est automatique.
    if type_installation == "offline_pur":
        print("[mode] Offline pur -- démarrage local, aucune synchro automatique.")
        demarrer_django_local(host="127.0.0.1")
        token = _charger_token_local()
        url_affichee = _url_avec_token(DJANGO_LOCAL_URL, token)
        creer_fenetre(config, url=url_affichee)
        webview.start()
        return

    role = config.get("role_reseau", "auto")
    serveur_local_url = (config.get("serveur_local_url") or "").strip()

    # --- Mode 1 : CLIENT d'un collègue en serveur_local sur le même réseau ---
    if role != "serveur_local" and serveur_local_url and adresse_joignable(serveur_local_url):
        print(f"[mode] Réseau local — connexion au poste serveur : {serveur_local_url}")
        token = _charger_token_local()
        url_affichee = _url_avec_token(serveur_local_url, token)
        fenetre = creer_fenetre(config, url=url_affichee)
        # Pas de Django local, pas de base locale, pas de worker de synchro
        # sur CE poste : le poste serveur s'en charge pour tout le bureau.
        webview.start()
        return

    # --- Mode 2 : EN LIGNE ---
    en_ligne = internet_disponible(config["serveur_backend"])
    if en_ligne and role != "serveur_local":
        print("[mode] En ligne — utilisation directe du serveur Render.")
        fenetre = creer_fenetre(config, url=config["url"])

        # Voir correctif n°2 en tête de fichier : le serveur Django local
        # doit tourner MAINTENANT, pendant qu'on est en ligne, sinon le
        # worker de synchro (juste en dessous) n'a personne à qui parler et
        # la base locale reste vide pour toujours — c'était la vraie cause
        # de l'échec de connexion et des données manquantes hors ligne.
        # Invisible pour l'utilisateur : la fenêtre affichée ci-dessus
        # continue de pointer vers Render, seul un serveur en tâche de fond
        # démarre en plus, sur 127.0.0.1 uniquement (jamais exposé au
        # réseau local ici — ce n'est pas le rôle "serveur_local").
        print("[mode] Démarrage du serveur local en tâche de fond (pour la synchronisation)...")
        demarrer_django_local(host="127.0.0.1")

        # CORRECTIF N°4 : sync_worker.py lit le token via la variable
        # d'environnement ERP_TOKEN_PATH, positionnée comme simple effet de
        # bord de _chemin_token() (voir plus haut). Mais rien dans ce Mode 2
        # n'appelait jamais cette fonction : si l'utilisateur était DÉJÀ
        # connecté (token encore valide dans le localStorage du navigateur
        # embarqué, donc Api.enregistrer_token jamais rappelé cette session),
        # la variable d'environnement restait vide et le worker de synchro
        # ne pouvait JAMAIS s'authentifier -- "Aucun token disponible" en
        # boucle, la base locale ne se remplissait donc jamais, même après
        # des heures en ligne : c'était la vraie cause de l'échec
        # systématique de la connexion hors ligne.
        _charger_token_local()

        from sync_worker import demarrer_boucle_synchro
        demarrer_boucle_synchro(config["serveur_backend"], DJANGO_LOCAL_URL, _device_id(config))
        webview.start()
        return

    # --- Mode 3 : SERVEUR LOCAL (bureau partagé) ou ISOLÉ ---
    host_ecoute = "0.0.0.0" if role == "serveur_local" else "127.0.0.1"
    if role == "serveur_local":
        print("[mode] Serveur local — démarrage, les collègues du bureau pourront s'y connecter.")
    else:
        print("[mode] Isolé — démarrage du serveur local (synchronisation différée).")

    demarrer_django_local(host=host_ecoute)

    token = _charger_token_local()
    if token and token.get("access"):
        print("[offline] Token local trouvé — connexion automatique.")
    else:
        print("[offline] Aucun token local trouvé — l'utilisateur devra se "
              "connecter au moins une fois EN LIGNE avant de pouvoir "
              "utiliser ce mode.")
    url_affichee = _url_avec_token(DJANGO_LOCAL_URL, token)
    fenetre = creer_fenetre(config, url=url_affichee)

    if role == "serveur_local":
        ip = obtenir_ip_locale()
        print(f"[mode] Adresse à donner aux collègues du bureau : http://{ip}:{DJANGO_LOCAL_PORT}")

    from sync_worker import demarrer_boucle_synchro
    demarrer_boucle_synchro(config["serveur_backend"], DJANGO_LOCAL_URL, _device_id(config))

    webview.start()


if __name__ == "__main__":
    main()
