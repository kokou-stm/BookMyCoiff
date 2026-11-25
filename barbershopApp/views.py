"""
API BookMyCoiff.

Public (clients, sans connexion)
    GET  /api/salons/                          liste des salons publiés (filtres + tri par distance)
    GET  /api/salons/<slug>/                   fiche complète d'un salon
    GET  /api/professionals/<id>/availability/ plages disponibles d'un pro (?date=, ?days=)

Espace prestataire (connecté) : /api/manage/...
    salons, services, equipment, photos, opening-hours   → gérant du salon
    professionals                                        → gérant, ou le pro pour son propre profil
    working-hours, overrides                             → gérant, ou le pro lui-même
"""

from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import redirect, render
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .forms import OwnerSignupForm, SalonForm
from .models import (
    AvailabilityOverride,
    Equipment,
    OpeningHours,
    Professional,
    Salon,
    SalonPhoto,
    Service,
    WorkingHours,
)
from .search import SearchError, search_salons
from .serializers import (
    AvailabilityOverrideSerializer,
    EquipmentSerializer,
    OpeningHoursSerializer,
    ProfessionalSerializer,
    SalonDetailSerializer,
    SalonListSerializer,
    SalonPhotoSerializer,
    SalonSerializer,
    ServiceSerializer,
    WorkingHoursSerializer,
)

MAX_AVAILABILITY_DAYS = 14


def managed_professionals(user):
    """Pros qu'un utilisateur peut gérer : ceux de ses salons + son propre profil."""
    if not user.is_authenticated:
        return Professional.objects.none()
    return Professional.objects.filter(Q(salon__owner=user) | Q(user=user)).distinct()


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


class SalonViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Salons publiés.

    Filtres : ?city=  ?search=  ?home_service=true  ?service_category=braids
    Proximité : ?lat=&lng=  (trie par distance, ajoute distance_km)  &radius_km=
    """

    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_serializer_class(self):
        return SalonDetailSerializer if self.action == "retrieve" else SalonListSerializer

    def get_queryset(self):
        return Salon.objects.filter(is_published=True).prefetch_related(
            "photos", "services", "equipment", "opening_hours",
            Prefetch("professionals", queryset=Professional.objects.prefetch_related("services")),
        )

    def list(self, request, *args, **kwargs):
        try:
            salons = search_salons(request.query_params)
        except SearchError as exc:
            raise serializers.ValidationError(exc.args[0])
        page = self.paginate_queryset(salons)
        serializer = self.get_serializer(page if page is not None else salons, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)


class ProfessionalAvailabilityViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.AllowAny]
    queryset = Professional.objects.filter(salon__is_published=True).select_related("salon")

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        """?date=YYYY-MM-DD (défaut : aujourd'hui)  ?days=N (1 à 14, défaut 1)"""
        professional = self.get_object()
        try:
            start = date.fromisoformat(request.query_params.get("date", date.today().isoformat()))
            days = int(request.query_params.get("days", 1))
        except ValueError:
            raise serializers.ValidationError("Paramètres invalides : date=AAAA-MM-JJ, days=entier.")
        if not 1 <= days <= MAX_AVAILABILITY_DAYS:
            raise serializers.ValidationError({"days": f"Entre 1 et {MAX_AVAILABILITY_DAYS}."})

        result = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            result.append({
                "date": day.isoformat(),
                "ranges": [
                    {"start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
                    for s, e in professional.availability_for(day)
                ],
            })
        return Response({"professional": professional.id, "days": result})


# ---------------------------------------------------------------------------
# Espace prestataire
# ---------------------------------------------------------------------------


class ManageSalonViewSet(viewsets.ModelViewSet):
    """Salons dont l'utilisateur est gérant."""

    serializer_class = SalonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Salon.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class OwnedBySalonViewSet(viewsets.ModelViewSet):
    """Objets rattachés à un salon : seul le gérant y accède. Filtre optionnel ?salon=<id>."""

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def get_queryset(self):
        qs = self.model.objects.filter(salon__owner=self.request.user)
        if salon := self.request.query_params.get("salon"):
            qs = qs.filter(salon_id=salon)
        return qs


class ManageServiceViewSet(OwnedBySalonViewSet):
    model = Service
    serializer_class = ServiceSerializer


class ManageEquipmentViewSet(OwnedBySalonViewSet):
    model = Equipment
    serializer_class = EquipmentSerializer


class ManageSalonPhotoViewSet(OwnedBySalonViewSet):
    model = SalonPhoto
    serializer_class = SalonPhotoSerializer


class ManageOpeningHoursViewSet(OwnedBySalonViewSet):
    model = OpeningHours
    serializer_class = OpeningHoursSerializer


class IsSalonOwnerForDestructive(permissions.BasePermission):
    """Un pro peut modifier son profil, mais seul le gérant crée ou supprime un pro."""

    def has_permission(self, request, view):
        return view.action not in ("create", "destroy") or Salon.objects.filter(owner=request.user).exists()

    def has_object_permission(self, request, view, obj):
        return view.action != "destroy" or obj.salon.owner_id == request.user.id


class ManageProfessionalViewSet(viewsets.ModelViewSet):
    serializer_class = ProfessionalSerializer
    permission_classes = [permissions.IsAuthenticated, IsSalonOwnerForDestructive]

    def get_queryset(self):
        qs = managed_professionals(self.request.user).select_related("salon").prefetch_related("services")
        if salon := self.request.query_params.get("salon"):
            qs = qs.filter(salon_id=salon)
        return qs

    @action(detail=True, methods=["post"])
    def toggle_bookings(self, request, pk=None):
        """Flag ouvert / fermé actionnable par le barbier."""
        professional = self.get_object()
        professional.is_accepting_bookings = not professional.is_accepting_bookings
        professional.save(update_fields=["is_accepting_bookings", "updated_at"])
        return Response({"is_accepting_bookings": professional.is_accepting_bookings})


class OwnedByProfessionalViewSet(viewsets.ModelViewSet):
    """Objets rattachés à un pro. Filtre optionnel ?professional=<id>."""

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def get_queryset(self):
        qs = self.model.objects.filter(professional__in=managed_professionals(self.request.user))
        if professional := self.request.query_params.get("professional"):
            qs = qs.filter(professional_id=professional)
        return qs


class ManageWorkingHoursViewSet(OwnedByProfessionalViewSet):
    model = WorkingHours
    serializer_class = WorkingHoursSerializer


class ManageAvailabilityOverrideViewSet(OwnedByProfessionalViewSet):
    """Réglages du jour. Filtre supplémentaire ?date=YYYY-MM-DD."""

    model = AvailabilityOverride
    serializer_class = AvailabilityOverrideSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if day := self.request.query_params.get("date"):
            qs = qs.filter(date=day)
        return qs


# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------

HOME_PAGE_SIZE = 12


def home(request):
    """Page d'accueil : recherche, filtres rapides, cartes salon, fiche en fenêtre."""
    try:
        salons = search_salons(request.GET)
    except SearchError:
        # paramètre invalide (coordonnées, note) : on l'ignore plutôt que d'afficher une erreur
        params = request.GET.copy()
        for key in ("lat", "lng", "radius_km", "min_rating"):
            params.pop(key, None)
        salons = search_salons(params)

    page = Paginator(salons, HOME_PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("salon", None)

    return render(request, "barbershopApp/home.html", {
        "page": page,
        "service_tiles": _service_tiles(query),
        "filters": {
            "search": request.GET.get("search", ""),
            "where": request.GET.get("where", ""),
            "service_category": request.GET.get("service_category", ""),
            "home_service": request.GET.get("home_service") == "true",
            "open": request.GET.get("open") == "true",
            "min_rating": request.GET.get("min_rating", ""),
            "lat": request.GET.get("lat", ""),
            "lng": request.GET.get("lng", ""),
        },
        "located": isinstance(salons, list),
        "active_filters": sum((
            bool(request.GET.get("service_category")),
            request.GET.get("home_service") == "true",
            request.GET.get("open") == "true",
            bool(request.GET.get("min_rating")),
        )),
        "querystring": query.urlencode(),
        "currency": getattr(settings, "BOOKMYCOIFF_CURRENCY", ""),
    })


def _service_tiles(query):
    """Tuiles « Trouver par service » : chaque tuile active / désactive son filtre de catégorie."""
    current = query.get("service_category", "")
    tiles = []
    for value, label in Service.Category.choices:
        params = query.copy()
        params.pop("service_category", None)
        if value != current:
            params["service_category"] = value
        tiles.append({"key": value, "label": label, "active": value == current, "url": "?" + params.urlencode()})

    return tiles


# ---------------------------------------------------------------------------
# Pages prestataire : inscription d'un salon (sans passer par l'admin)
# ---------------------------------------------------------------------------


def salon_register(request):
    """Inscrire mon salon : crée le compte du gérant (s'il n'est pas connecté) puis le salon."""
    needs_account = not request.user.is_authenticated
    if request.method == "POST":
        account_form = OwnerSignupForm(request.POST, prefix="account") if needs_account else None
        salon_form = SalonForm(request.POST, request.FILES)
        if salon_form.is_valid() and (account_form is None or account_form.is_valid()):
            with transaction.atomic():
                owner = account_form.save() if account_form else request.user
                salon = salon_form.save(owner=owner)
            if account_form:
                login(request, owner, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"« {salon.name} » est en ligne : les clients peuvent déjà le trouver.")
            return redirect("my_salons")
    else:
        account_form = OwnerSignupForm(prefix="account") if needs_account else None
        salon_form = SalonForm()
    return render(request, "barbershopApp/salon_register.html", {
        "account_form": account_form, "form": salon_form,
    })


@login_required
def my_salons(request):
    salons = request.user.owned_salons.prefetch_related("opening_hours", "professionals").order_by("-created_at")
    return render(request, "barbershopApp/my_salons.html", {"salons": salons})
