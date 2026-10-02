from django.urls import path

from .views import (
    CreerSocietePremierDemarrageView,
    EtatPremierDemarrageView,
    PremierDemarrageView,
)

urlpatterns = [
    path("premier-demarrage/etat/", EtatPremierDemarrageView.as_view(), name="premier-demarrage-etat"),
    path("premier-demarrage/initialiser/", PremierDemarrageView.as_view(), name="premier-demarrage-initialiser"),
    path("premier-demarrage/entreprise/", CreerSocietePremierDemarrageView.as_view(), name="premier-demarrage-entreprise"),
]
