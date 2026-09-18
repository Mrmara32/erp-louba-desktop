"""
Service de synchronisation exécuté dans un thread d'arrière-plan par
app.py, tant que l'exécutable desktop tourne. Ne fait rien tant qu'aucune
connexion internet n'est détectée ; dès que le serveur redevient joignable,
pousse les documents en attente puis tire les mises à jour du référentiel.

Dépend d'un token JWT déjà obtenu (stocké après une connexion en ligne
réussie, voir token_store.py) — un poste qui n'a jamais eu de connexion ne
peut pas synchroniser tant que l'utilisateur ne s'est pas connecté au moins
une fois avec internet.
"""
import json
import os
import socket
import threading
import time

import requests

INTERVALLE_SECONDES = 60
TOKEN_PATH_ENV = "ERP_TOKEN_PATH"


def internet_disponible(hote="erp-louba-backend.onrender.com", port=443, timeout=3):
    try:
        socket.create_connection((hote, port), timeout=timeout)
        return True
    except OSError:
        return False


def _charger_token():
    chemin = os.environ.get(TOKEN_PATH_ENV, "")
    if chemin and os.path.exists(chemin):
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _rafraichir_token_si_necessaire(serveur_url):
    """
    Le token d'accès expire après 8h (SIMPLE_JWT côté serveur) — un poste
    resté hors-ligne plus longtemps aurait un token périmé au moment de la
    synchro. On rafraîchit systématiquement AVANT de synchroniser plutôt que
    d'attendre un 401, pour garder ce module simple et prévisible.
    """
    donnees = _charger_token()
    if not donnees or not donnees.get("refresh"):
        return
    try:
        reponse = requests.post(
            f"{serveur_url}/api/auth/token/refresh/",
            json={"refresh": donnees["refresh"]},
            timeout=10,
        )
        reponse.raise_for_status()
        donnees["access"] = reponse.json()["access"]
        chemin = os.environ.get(TOKEN_PATH_ENV, "")
        if chemin:
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(donnees, f)
    except requests.RequestException as e:
        print(f"[synchro] Rafraîchissement du token impossible (sera retenté au prochain cycle) : {e}")


def _entetes():
    donnees = _charger_token()
    token = donnees.get("access") if donnees else None
    return {"Authorization": f"Bearer {token}"} if token else {}


def synchroniser_une_fois(serveur_url, django_local_url, device_id):
    """
    1. Interroge la base locale (via l'API Django locale elle-même, pas
       directement SQLite) pour la liste des documents non synchronisés.
    2. Les pousse vers le serveur central.
    3. Tire les mises à jour du référentiel depuis le serveur.
    Toute erreur est journalisée mais ne fait jamais planter l'application —
    la synchro réessaiera au prochain cycle.
    """
    entetes = _entetes()
    if not entetes:
        print("[synchro] Aucun token disponible, connexion en ligne requise au moins une fois.")
        return

    _rafraichir_token_si_necessaire(serveur_url)
    entetes = _entetes()

    try:
        # 1-2. Documents en attente -> push
        reponse = requests.get(
            f"{django_local_url}/api/synchro/documents-en-attente/", headers=entetes, timeout=10
        )
        reponse.raise_for_status()
        documents = reponse.json().get("documents", [])
        if documents:
            push = requests.post(
                f"{serveur_url}/api/synchro/push-documents/",
                json={"device_id": device_id, "documents": documents},
                headers=entetes,
                timeout=30,
            )
            push.raise_for_status()
            requests.post(
                f"{django_local_url}/api/synchro/appliquer-resultats-push/",
                json=push.json(),
                headers=entetes,
                timeout=10,
            )
            print(f"[synchro] {len(documents)} document(s) synchronisé(s).")

        # 3. Référentiel -> pull
        pull = requests.get(
            f"{serveur_url}/api/synchro/pull-referentiel/", headers=entetes, timeout=30
        )
        pull.raise_for_status()
        requests.post(
            f"{django_local_url}/api/synchro/importer-referentiel/",
            json=pull.json(),
            headers=entetes,
            timeout=30,
        )
        print("[synchro] Référentiel à jour.")

    except requests.RequestException as e:
        print(f"[synchro] Échec de synchronisation, nouvelle tentative dans {INTERVALLE_SECONDES}s : {e}")


def demarrer_boucle_synchro(serveur_url, django_local_url, device_id):
    def boucle():
        while True:
            if internet_disponible():
                synchroniser_une_fois(serveur_url, django_local_url, device_id)
            time.sleep(INTERVALLE_SECONDES)

    thread = threading.Thread(target=boucle, daemon=True)
    thread.start()
    return thread
