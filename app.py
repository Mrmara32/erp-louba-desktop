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
"""
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import urlparse
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


def _injecter_token_dans_page(window, token):
    script = f"localStorage.setItem('access_token', {json.dumps(token.get('access', ''))});"
    if token.get("refresh"):
        script += f"localStorage.setItem('refresh_token', {json.dumps(token['refresh'])});"

    def _quand_charge():
        try:
            window.evaluate_js(script)
        except Exception as e:
            print(f"[offline] Injection du token impossible : {e}")

    window.events.loaded += _quand_charge


def main():
    config = charger_config()
    role = config.get("role_reseau", "auto")
    serveur_local_url = (config.get("serveur_local_url") or "").strip()

    # --- Mode 1 : CLIENT d'un collègue en serveur_local sur le même réseau ---
    if role != "serveur_local" and serveur_local_url and adresse_joignable(serveur_local_url):
        print(f"[mode] Réseau local — connexion au poste serveur : {serveur_local_url}")
        fenetre = creer_fenetre(config, url=serveur_local_url)
        # Pas de Django local, pas de base locale, pas de worker de synchro
        # sur CE poste : le poste serveur s'en charge pour tout le bureau.
        webview.start()
        return

    # --- Mode 2 : EN LIGNE ---
    en_ligne = internet_disponible(config["serveur_backend"])
    if en_ligne and role != "serveur_local":
        print("[mode] En ligne — utilisation directe du serveur Render.")
        fenetre = creer_fenetre(config, url=config["url"])
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
    url_affichee = DJANGO_LOCAL_URL
    fenetre = creer_fenetre(config, url=url_affichee)

    token = _charger_token_local()
    if token and token.get("access"):
        _injecter_token_dans_page(fenetre, token)
    else:
        print("[offline] Aucun token local trouvé — l'utilisateur devra se "
              "connecter au moins une fois EN LIGNE avant de pouvoir "
              "utiliser ce mode.")

    if role == "serveur_local":
        ip = obtenir_ip_locale()
        print(f"[mode] Adresse à donner aux collègues du bureau : http://{ip}:{DJANGO_LOCAL_PORT}")

    from sync_worker import demarrer_boucle_synchro
    demarrer_boucle_synchro(config["serveur_backend"], DJANGO_LOCAL_URL, _device_id(config))

    webview.start()


if __name__ == "__main__":
    main()
