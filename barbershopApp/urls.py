from django.urls import include, path
from rest_framework import permissions
from rest_framework.routers import APIRootView, DefaultRouter

from . import views


class PublicAPIRootView(APIRootView):
    """Page d'accueil de l'API, visible sans connexion (les routes /manage/ restent protégées)."""

    permission_classes = [permissions.AllowAny]


class Router(DefaultRouter):
    APIRootView = PublicAPIRootView


router = Router()

# Public
router.register("salons", views.SalonViewSet, basename="salon")
router.register("professionals", views.ProfessionalAvailabilityViewSet, basename="professional")

# Espace prestataire
router.register("manage/salons", views.ManageSalonViewSet, basename="manage-salon")
router.register("manage/services", views.ManageServiceViewSet, basename="manage-service")
router.register("manage/equipment", views.ManageEquipmentViewSet, basename="manage-equipment")
router.register("manage/photos", views.ManageSalonPhotoViewSet, basename="manage-photo")
router.register("manage/opening-hours", views.ManageOpeningHoursViewSet, basename="manage-opening-hours")
router.register("manage/professionals", views.ManageProfessionalViewSet, basename="manage-professional")
router.register("manage/working-hours", views.ManageWorkingHoursViewSet, basename="manage-working-hours")
router.register("manage/overrides", views.ManageAvailabilityOverrideViewSet, basename="manage-override")

urlpatterns = [
    path("", include(router.urls)),
]
