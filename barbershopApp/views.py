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

from datetime import date, time, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .booking import (
    BookingError,
    available_times,
    bookable_professionals,
    can_cancel,
    cancel_booking,
    create_booking,
    days_with_slots,
    find_booking,
    local_now,
    normalize_code,
)
from .forms import BookingContactForm, BookingLookupForm, OwnerSignupForm, SalonForm
from .models import (
    AvailabilityOverride,
    Booking,
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


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "barbershopApp/password_change.html"
    success_url = reverse_lazy("my_salons")
    success_message = "Votre mot de passe a été modifié."


class PasswordResetView(auth_views.PasswordResetView):
    """Mot de passe oublié : envoie un lien par e-mail (désactivé tant qu'aucun SMTP n'est configuré)."""

    template_name = "barbershopApp/password_reset.html"
    email_template_name = "barbershopApp/emails/password_reset.txt"
    subject_template_name = "barbershopApp/emails/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")
    extra_email_context = {"site_name": "BookMyCoiff"}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "enabled": settings.EMAIL_ENABLED}

    def post(self, request, *args, **kwargs):
        if not settings.EMAIL_ENABLED:
            return self.get(request, *args, **kwargs)
        return super().post(request, *args, **kwargs)


def _login_existing_owner(request):
    """L'e-mail saisi a déjà un compte et le mot de passe est le bon : on connecte au lieu de refuser."""
    email = request.POST.get("account-email", "").strip().lower()
    password = request.POST.get("account-password1", "")
    if not email or not password:
        return False
    user = authenticate(request, username=email, password=password)
    if user is None:
        return False
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return True


def salon_register(request):
    """Inscrire mon salon : crée le compte du gérant (s'il n'est pas connecté) puis le salon."""
    needs_account = not request.user.is_authenticated
    if request.method == "POST":
        if needs_account and _login_existing_owner(request):
            needs_account = False
            # Double envoi (le 1er a déjà tout créé, sa réponse a été abandonnée par le navigateur)
            recent = request.user.owned_salons.filter(
                name__iexact=request.POST.get("name", "").strip(),
                created_at__gte=timezone.now() - timedelta(minutes=15),
            ).first()
            if recent:
                messages.success(request, f"« {recent.name} » est en ligne : les clients peuvent déjà le trouver.")
                return redirect("my_salons")
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
    upcoming = Booking.objects.filter(date__gte=local_now().date()).select_related("professional").order_by("date", "start_time")
    salons = request.user.owned_salons.prefetch_related(
        "opening_hours", "professionals", Prefetch("bookings", queryset=upcoming, to_attr="upcoming_bookings"),
    ).order_by("-created_at")
    return render(request, "barbershopApp/my_salons.html", {
        "salons": salons, "currency": getattr(settings, "BOOKMYCOIFF_CURRENCY", ""),
    })


# ---------------------------------------------------------------------------
# Réservation en ligne par les clients (sans compte : un code + le téléphone)
# ---------------------------------------------------------------------------

# Codes des réservations que ce navigateur a le droit de voir (faites ici, ou retrouvées avec le téléphone)
SESSION_BOOKINGS = "booking_codes"


def _remember_booking(request, code):
    codes = [c for c in request.session.get(SESSION_BOOKINGS, []) if c != code]
    request.session[SESSION_BOOKINGS] = (codes + [code])[-20:]


def _parse_day(value, allowed):
    try:
        day = date.fromisoformat(value or "")
    except ValueError:
        return None
    return day if day in allowed else None


def _group_times(minutes):
    groups = {"Matin": [], "Après-midi": [], "Soir": []}
    for m in minutes:
        label = f"{m // 60:02d}:{m % 60:02d}"
        groups["Matin" if m < 12 * 60 else "Après-midi" if m < 17 * 60 else "Soir"].append(label)
    return [(name, items) for name, items in groups.items() if items]


def booking_page(request, slug):
    """
    Réservation en une page, étape par étape via l'URL :
    ?service=<id> → &pro=<id|any> → &date=AAAA-MM-JJ → &time=HH:MM → coordonnées (POST).
    """
    salon = get_object_or_404(Salon.objects.filter(is_published=True), slug=slug)
    params = request.POST if request.method == "POST" else request.GET
    services = list(salon.services.filter(is_active=True))
    service = next((s for s in services if str(s.pk) == params.get("service")), None)

    pros = bookable_professionals(salon, service) if service else []
    pro_param = params.get("pro", "")
    professional = next((p for p in pros if str(p.pk) == pro_param), None)
    if service and len(pros) == 1:
        professional, pro_param = pros[0], str(pros[0].pk)  # un seul coiffeur : pas de choix à faire
    pro_chosen = bool(service and (professional or (pro_param == "any" and pros)))

    now = local_now()
    days = days_with_slots(salon, service, professional, now) if pro_chosen else []
    day = _parse_day(params.get("date"), [d for d, count in days if count])
    times = available_times(salon, service, day, professional, now) if day else {}
    start_label = params.get("time", "")
    start = next((m for m in times if f"{m // 60:02d}:{m % 60:02d}" == start_label), None)

    error = None
    form = BookingContactForm(request.POST if request.method == "POST" else None) if start is not None else None
    if request.method == "POST":
        if start is None:
            error = "Ce créneau n'est plus disponible. Choisissez une autre heure."
        elif form.is_valid():
            try:
                booking = create_booking(
                    salon=salon, service=service, professional=professional, day=day,
                    start=time(start // 60, start % 60), now=now, **form.cleaned_data,
                )
            except BookingError as exc:
                error = str(exc)
            else:
                _remember_booking(request, booking.code)
                return redirect(f"{reverse('booking_detail', args=[booking.code])}?new=1")

    def link(**choices):
        return "?" + urlencode({k: v for k, v in choices.items() if v not in (None, "")})

    return render(request, "barbershopApp/booking.html", {
        "salon": salon,
        "currency": getattr(settings, "BOOKMYCOIFF_CURRENCY", ""),
        "services": [{"obj": s, "url": link(service=s.pk), "active": s == service} for s in services],
        "service": service,
        "pros": [{"obj": p, "url": link(service=service.pk, pro=p.pk), "active": p == professional} for p in pros] if service else [],
        "any_pro_url": link(service=service.pk, pro="any") if service else "",
        "any_pro_active": pro_param == "any" and professional is None,
        "professional": professional,
        "pro_param": pro_param,
        "pro_chosen": pro_chosen,
        "days": [{"day": d, "count": c, "active": d == day,
                  "url": link(service=service.pk, pro=pro_param, date=d.isoformat())} for d, c in days],
        "day": day,
        "has_slots": any(count for _, count in days),
        "time_groups": [
            (name, [{"label": t, "active": t == start_label and start is not None,
                     "url": link(service=service.pk, pro=pro_param, date=day.isoformat(), time=t)} for t in items])
            for name, items in _group_times(times)
        ] if day else [],
        "start_label": start_label if start is not None else "",
        "form": form,
        "error": error,
    })


def booking_detail(request, code):
    code = normalize_code(code)
    if code not in request.session.get(SESSION_BOOKINGS, []):
        return redirect(f"{reverse('booking_lookup')}?{urlencode({'code': code})}")
    booking = get_object_or_404(Booking.objects.select_related("salon", "professional"), code=code)
    return render(request, "barbershopApp/booking_detail.html", {
        "booking": booking,
        "can_cancel": can_cancel(booking),
        "just_booked": request.GET.get("new") == "1",
        "currency": getattr(settings, "BOOKMYCOIFF_CURRENCY", ""),
    })


def booking_cancel(request, code):
    code = normalize_code(code)
    if request.method != "POST" or code not in request.session.get(SESSION_BOOKINGS, []):
        return redirect("booking_detail", code=code)
    booking = get_object_or_404(Booking, code=code)
    try:
        cancel_booking(booking)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Votre réservation est annulée. Le créneau est libéré pour d'autres clients.")
    return redirect("booking_detail", code=code)


def booking_lookup(request):
    """Retrouver une réservation avec son code + le téléphone utilisé."""
    form = BookingLookupForm(request.POST or None, initial={"code": request.GET.get("code", "")})
    not_found = False
    if request.method == "POST" and form.is_valid():
        booking = find_booking(form.cleaned_data["code"], form.cleaned_data["phone"])
        if booking:
            _remember_booking(request, booking.code)
            return redirect("booking_detail", code=booking.code)
        not_found = True
    return render(request, "barbershopApp/booking_lookup.html", {"form": form, "not_found": not_found})
