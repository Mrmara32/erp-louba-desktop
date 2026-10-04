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


def _renouveler_plages_numeros(serveur_url, django_local_url, device_id, entetes):
    """
    Étape "100% hors-ligne" : tant qu'une connexion est disponible, demande
    au poste local ce qui a besoin d'être renouvelé (plages de numéros
    bientôt épuisées ou jamais réservées), réserve les blocs correspondants
    auprès du serveur central, puis les enregistre localement. C'est ce qui
    permet ensuite au poste d'attribuer des numéros réels et définitifs
    même totalement hors connexion (voir societes/sequences.py côté
    backend).

    N'interrompt jamais la synchro documentaire/référentiel en cas d'échec :
    une erreur ici est journalisée et retentée au prochain cycle, le poste
    continue simplement à utiliser des numéros provisoires "OFF-" en
    attendant.
    """
    try:
        etat = requests.get(
            f"{django_local_url}/api/synchro/plages-locales/", headers=entetes, timeout=10
        )
        etat.raise_for_status()
        a_renouveler = etat.json().get("plages_a_renouveler", [])
    except requests.RequestException as e:
        print(f"[synchro] Impossible de lire l'état des plages locales : {e}")
        return

    for entree in a_renouveler:
        societe_id = entree["societe_id"]
        for besoin in entree.get("besoins", []):
            try:
                reservation = requests.post(
                    f"{serveur_url}/api/synchro/reserver-plage/",
                    json={
                        "device_id": device_id,
                        "societe": societe_id,
                        "prefixe": besoin["prefixe"],
                        "largeur": besoin["largeur"],
                    },
                    headers=entetes,
                    timeout=15,
                )
                reservation.raise_for_status()
                plage = reservation.json()

                enregistrement = requests.post(
                    f"{django_local_url}/api/synchro/enregistrer-plage/",
                    json={
                        "societe_id": societe_id,
                        "device_id": device_id,
                        "prefixe": plage["prefixe"],
                        "largeur": plage["largeur"],
                        "numero_debut": plage["numero_debut"],
                        "numero_fin": plage["numero_fin"],
                    },
                    headers=entetes,
                    timeout=10,
                )
                enregistrement.raise_for_status()
                print(
                    f"[synchro] Plage réservée pour {besoin['prefixe']} "
                    f"({entree['societe_code']}) : {plage['numero_debut']}-{plage['numero_fin']}."
                )
            except requests.RequestException as e:
                print(f"[synchro] Échec de réservation de plage pour {besoin['prefixe']} : {e}")


def synchroniser_une_fois(serveur_url, django_local_url, device_id):
    """
    1. Interroge la base locale (via l'API Django locale elle-même, pas
       directement SQLite) pour la liste des documents non synchronisés.
    2. Les pousse vers le serveur central.
    3. Tire les mises à jour du référentiel depuis le serveur.
    4. Renouvelle les plages de numéros réservées, si nécessaire, pour que
       le poste reste capable d'attribuer des numéros définitifs même
       lorsqu'il repassera hors-ligne (voir _renouveler_plages_numeros).
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
        importer = requests.post(
            f"{django_local_url}/api/synchro/importer-referentiel/",
            json=pull.json(),
            headers=entetes,
            timeout=30,
        )
        # IMPORTANT : sans ce raise_for_status(), un 500 cote local (ex.
        # ValueError sur un champ FK du référentiel) était silencieusement
        # ignoré et "[synchro] Référentiel à jour." s'affichait quand même,
        # masquant l'échec réel de l'import.
        importer.raise_for_status()
        print("[synchro] Référentiel à jour.")

    except requests.RequestException as e:
        print(f"[synchro] Échec de synchronisation, nouvelle tentative dans {INTERVALLE_SECONDES}s : {e}")
        return

    # 4. Renouvellement des plages de numéros (indépendant du bloc ci-dessus :
    # un échec ici ne doit pas être traité comme un échec de synchro globale).
    _renouveler_plages_numeros(serveur_url, django_local_url, device_id, entetes)


def demarrer_boucle_synchro(serveur_url, django_local_url, device_id):
    def boucle():
        while True:
            if internet_disponible():
                synchroniser_une_fois(serveur_url, django_local_url, device_id)
            time.sleep(INTERVALLE_SECONDES)

    thread = threading.Thread(target=boucle, daemon=True)
    thread.start()
    return thread
