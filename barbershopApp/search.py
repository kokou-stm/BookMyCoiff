"""Recherche de salons, partagée par la page d'accueil et l'API."""

import math

from django.db.models import Min, Q

from .models import Professional, Salon, Service


class SearchError(ValueError):
    """Paramètre de recherche invalide. args[0] = {champ: message}."""


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(math.radians, map(float, (lat1, lng1, lat2, lng2)))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _float(params, name):
    try:
        return float(params[name])
    except (TypeError, ValueError):
        raise SearchError({name: "Nombre attendu."})


def published_salons():
    return (
        Salon.objects.filter(is_published=True)
        .prefetch_related("photos")
        .annotate(min_price=Min("services__price", filter=Q(services__is_active=True)))
        # Meta.ordering est ignoré avec un GROUP BY : ordre explicite pour une pagination stable
        .order_by("name")
    )


def search_salons(params):
    """
    Filtres : search (quoi), where (où), city, service_category, home_service=true,
              open=true (accepte les réservations), min_rating
    Proximité : lat + lng (tri par distance, ajoute salon.distance_km), radius_km

    Renvoie un QuerySet, ou une liste triée par distance si lat/lng sont fournis.
    Le tri par distance se fait en Python : suffisant tant qu'il y a peu de salons,
    à remplacer par PostGIS quand le volume grandira.
    """
    qs = published_salons()

    if search := params.get("search", "").strip():
        # « Quoi » : nom du salon, d'un service ou d'un coiffeur
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(id__in=Service.objects.filter(name__icontains=search, is_active=True).values("salon_id"))
            | Q(id__in=Professional.objects.filter(display_name__icontains=search, is_active=True).values("salon_id"))
        )
    if where := params.get("where", "").strip():
        # « Où » : ville, quartier ou adresse
        qs = qs.filter(Q(city__icontains=where) | Q(address__icontains=where))
    if city := params.get("city", "").strip():
        qs = qs.filter(city__iexact=city)
    if params.get("home_service") == "true":
        qs = qs.filter(offers_home_service=True)
    if params.get("open") == "true":
        qs = qs.filter(is_accepting_bookings=True)
    if min_rating := params.get("min_rating"):
        try:
            qs = qs.filter(base_rating__gte=float(min_rating))
        except ValueError:
            raise SearchError({"min_rating": "Nombre attendu."})
    if category := params.get("service_category"):
        qs = qs.filter(
            id__in=Service.objects.filter(category=category, is_active=True).values("salon_id")
        )

    if not (params.get("lat") and params.get("lng")):
        return qs

    lat, lng = _float(params, "lat"), _float(params, "lng")
    radius = _float(params, "radius_km") if params.get("radius_km") else None
    salons = []
    for salon in qs:
        salon.distance_km = haversine_km(lat, lng, salon.latitude, salon.longitude)
        if radius is None or salon.distance_km <= radius:
            salons.append(salon)
    salons.sort(key=lambda s: s.distance_km)
    return salons
