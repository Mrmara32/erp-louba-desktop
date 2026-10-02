"""Configuration des URLs du projet ERP Comptabilité & Logistique."""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),

    # Authentification JWT
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # APIs métier
    path('api/', include('utilisateurs.urls')),
    path('api/', include('comptes.urls')),
    path('api/', include('journaux.urls')),
    path('api/', include('tresorerie.urls')),
    path('api/', include('logistique.urls')),
    path('api/', include('etats.urls')),
    path('api/', include('notifications.urls')),
    path('api/', include('entreprise.urls')),
    path('api/', include('licences.urls')),
    path('api/', include('paie.urls')),
    path('api/', include('demandes.urls')),
    path('api/', include('societes.urls')),
    path('api/', include('ventes.urls')),
    path('api/', include('stocks.urls')),
    path('api/', include('demarrage.urls')),

    # Synchronisation offline (pull référentiel / push documents)
    path('api/synchro/', include('synchro.urls')),
]

# En développement (DEBUG=True), Django sert lui-même les fichiers uploadés
# (logo, etc.). En production, ceci doit être servi par le serveur web
# (Nginx, etc.), pas par Django.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Mode offline uniquement : Django sert directement le frontend React buildé
# (voir synchro/frontend_offline.py). Placé en tout dernier — un catch-all
# doit toujours arriver après toutes les routes /api/ et /admin/, sinon il
# les intercepterait avant qu'elles ne soient jamais atteintes.
if getattr(settings, "OFFLINE_MODE", False):
    from synchro.frontend_offline import servir_assets, servir_index

    urlpatterns += [
        re_path(r"^assets/(?P<path>.*)$", servir_assets, name="frontend-assets"),
        re_path(r"^(?!api/|admin/).*$", servir_index, name="frontend-catchall"),
    ]
