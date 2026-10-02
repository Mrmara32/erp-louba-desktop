"""
App "demarrage" : assistant de premier démarrage pour les postes OFFLINE
(100% hors-ligne, ou offline-syncro avant toute première synchronisation).

Au tout premier lancement, la base locale est vide : aucun Utilisateur,
aucune Societe. Ces vues permettent de créer, une seule fois, le compte
administrateur de ce poste puis, si besoin, les informations de
l'entreprise -- sans jamais passer par le serveur central (indispensable en
100% hors-ligne, qui n'y a de toute façon jamais accès).

SÉCURITÉ : EtatPremierDemarrageView et PremierDemarrageView sont ouvertes
(AllowAny) mais PremierDemarrageView se verrouille elle-même dès qu'un
compte existe déjà localement (403) -- elle ne peut donc servir qu'une
seule fois par poste, à l'installation, jamais ensuite (même principe que
le correctif appliqué sur l'activation de licence : une porte ouverte
"juste pour l'installation" doit se refermer d'elle-même).
CreerSocietePremierDemarrageView exige d'être authentifié et que le compte
connecté n'ait pas déjà de société (donc, en pratique, seulement juste
après l'étape précédente).
"""
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from entreprise.models import Entreprise
from societes.models import Societe
from utilisateurs.models import Role

Utilisateur = get_user_model()


class EtatPremierDemarrageView(APIView):
    """
    GET /api/premier-demarrage/etat/ -- indique si ce poste a déjà un compte
    et/ou une société configurés, pour que le frontend sache s'il doit
    afficher l'assistant de premier démarrage (et laquelle de ses étapes).
    Toujours vrai sur le serveur central (Render) une fois en production,
    puisqu'il y a toujours au moins un utilisateur réel -- l'assistant ne
    peut donc jamais s'afficher par erreur en ligne.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(
            {
                "compte_existe": Utilisateur.objects.exists(),
                "societe_existe": Societe.objects.exists(),
            }
        )


class PremierDemarrageView(APIView):
    """
    POST /api/premier-demarrage/initialiser/ -- crée le tout premier compte
    administrateur de ce poste.

    Body attendu :
      {
        "mode": "windows" | "existant",
        "username": "...",
        "password": "...",
        "nom_complet": "..." (optionnel),
        "email": "..." (optionnel)
      }

    Les deux modes créent un compte ADMINISTRATEUR (is_superuser=True) sur
    CE poste uniquement :
      - "windows" : compte lié au nom de session Windows du poste.
      - "existant" : recopie locale d'un compte déjà vérifié par le serveur
        central (la vérification a lieu côté application desktop, voir
        Api.valider_compte_central dans erp-desktop/app.py, pour éviter tout
        problème de CORS depuis une page servie localement) -- cela ne
        change rien à son rôle sur le serveur central, seulement à son rôle
        SUR CE POSTE précis.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if Utilisateur.objects.exists():
            return Response(
                {"detail": "Un compte existe déjà sur ce poste. Cette étape ne peut servir qu'une seule fois."},
                status=403,
            )

        mode = request.data.get("mode")
        if mode not in ("windows", "existant"):
            return Response({"detail": "Mode invalide."}, status=400)

        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response({"detail": "Nom d'utilisateur et mot de passe requis."}, status=400)
        if len(password) < 6:
            return Response({"detail": "Le mot de passe doit contenir au moins 6 caractères."}, status=400)

        nom_complet = (request.data.get("nom_complet") or "").strip()
        prenom, _, nom = nom_complet.partition(" ")

        utilisateur = Utilisateur.objects.create_user(
            username=username,
            password=password,
            email=(request.data.get("email") or ""),
            first_name=prenom,
            last_name=nom,
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )

        refresh = RefreshToken.for_user(utilisateur)
        return Response(
            {
                "ok": True,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "societe_existe": Societe.objects.exists(),
            },
            status=201,
        )


class PeutCreerSocietePremierDemarrage(permissions.BasePermission):
    message = "Cette étape n'est accessible qu'une fois, juste après la création du compte administrateur."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.societe_id is None
        )


class CreerSocietePremierDemarrageView(APIView):
    """
    POST /api/premier-demarrage/entreprise/ -- renseigne, une seule fois,
    les informations de la société pour ce poste (raison sociale, adresse,
    contacts...), indispensable en 100% hors-ligne puisqu'il n'y aura jamais
    de serveur central pour les fournir autrement. Charge aussitôt le plan
    comptable SYSCOHADA et les journaux/exercice/trésorerie de base pour que
    la société soit utilisable immédiatement (voir
    Societe.initialiser_donnees_de_base). Modifiable ensuite à tout moment
    par un administrateur depuis la page Entreprise (entreprise.views.EntrepriseView).
    """
    permission_classes = [PeutCreerSocietePremierDemarrage]

    def post(self, request):
        nom = (request.data.get("nom") or "").strip()
        if not nom:
            return Response({"detail": "La raison sociale est obligatoire."}, status=400)

        code_base = (slugify(nom).replace("-", "")[:20] or "SOCIETE").upper()
        code = code_base
        suffixe = 1
        while Societe.objects.filter(code=code).exists():
            suffixe += 1
            code = f"{code_base}{suffixe}"

        societe = Societe.objects.create(
            code=code,
            nom=nom,
            est_societe_mere=True,
            actif=True,
            adresse_ligne1=(request.data.get("adresse_ligne1") or ""),
            ville=(request.data.get("ville") or ""),
            pays=(request.data.get("pays") or "Guinée"),
            telephone=(request.data.get("telephone") or ""),
            email=(request.data.get("email") or ""),
            nif=(request.data.get("nif") or ""),
        )
        societe.initialiser_donnees_de_base()

        from licences.models import Licence
        Licence.get_pour_societe(societe)

        request.user.societe = societe
        request.user.save(update_fields=["societe"])

        entreprise = Entreprise.get_pour_societe(societe)
        entreprise.nom = nom
        entreprise.adresse_ligne1 = societe.adresse_ligne1
        entreprise.ville = societe.ville
        entreprise.pays = societe.pays
        entreprise.telephone = societe.telephone
        entreprise.email = societe.email
        entreprise.nif = societe.nif
        entreprise.save()

        return Response({"ok": True, "societe_id": societe.id}, status=201)
