"""
Réservation en ligne : calcul des créneaux libres et création / annulation d'une réservation.

Un créneau est libre pour un coiffeur si :
- il tombe dans ses disponibilités du jour (horaires + ajustements, voir Professional.availability_for) ;
- il ne chevauche aucune de ses réservations confirmées ;
- le salon a encore un poste libre sur toute la durée (workstation_count) ;
- il commence au moins MIN_NOTICE_MINUTES après maintenant, et au plus DAYS_AHEAD jours plus tard.
La durée bloquée est celle du service + sa marge (Service.blocked_minutes).
"""

import re
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Booking, Salon, _subtract

SLOT_STEP_MINUTES = 15
MIN_NOTICE_MINUTES = 30
DAYS_AHEAD = 14
MAX_ACTIVE_BOOKINGS_PER_PHONE = 3  # par salon, contre les réservations en masse


class BookingError(Exception):
    """Réservation impossible ; le message est affiché tel quel au client."""


# --- Utilitaires -----------------------------------------------------------

def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def phone_key(phone: str) -> str:
    """Les 8 derniers chiffres : « +228 90 11 22 33 » et « 90112233 » désignent le même numéro."""
    return re.sub(r"\D", "", phone or "")[-8:]


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", code or "").upper()


def local_now():
    return timezone.localtime()


def starts_at(booking: Booking):
    return timezone.make_aware(datetime.combine(booking.date, booking.start_time))


def booking_days(now=None):
    today = (now or local_now()).date()
    return [today + timedelta(days=i) for i in range(DAYS_AHEAD + 1)]


# --- Créneaux ---------------------------------------------------------------

def bookable_professionals(salon, service):
    """Coiffeurs qui réalisent ce service (un coiffeur sans liste de services les fait tous)."""
    pros = salon.professionals.filter(is_active=True, is_accepting_bookings=True).prefetch_related("services")
    return [p for p in pros if not p.services.all() or any(s.pk == service.pk for s in p.services.all())]


def _confirmed(qs):
    return qs.filter(status=Booking.Status.CONFIRMED)


def available_times(salon, service, day, professional=None, now=None):
    """
    {minute de début: [coiffeurs libres]} pour `day`, trié par heure.
    `professional=None` : n'importe quel coiffeur du salon qui fait ce service.
    """
    now = now or local_now()
    today = now.date()
    if not (salon.is_published and salon.is_accepting_bookings and service.is_active):
        return {}
    if day < today or day > today + timedelta(days=DAYS_AHEAD):
        return {}

    pros = [professional] if professional else bookable_professionals(salon, service)
    day_bookings = list(_confirmed(salon.bookings.filter(date=day)).values_list("professional_id", "start_time", "end_time"))
    salon_busy = [(_minutes(s), _minutes(e)) for _, s, e in day_bookings]
    need = service.blocked_minutes
    earliest = now.hour * 60 + now.minute + MIN_NOTICE_MINUTES if day == today else 0

    times: dict[int, list] = {}
    for pro in pros:
        ranges = pro.availability_for(day)
        for pro_id, s, e in day_bookings:
            if pro_id == pro.pk:
                ranges = _subtract(ranges, (s, e))
        for start, end in ranges:
            # Premier départ sur la grille de 15 min, pas avant `earliest`
            m = -(-max(_minutes(start), earliest) // SLOT_STEP_MINUTES) * SLOT_STEP_MINUTES
            while m + need <= _minutes(end):
                busy_stations = sum(1 for bs, be in salon_busy if bs < m + need and be > m)
                if busy_stations < salon.workstation_count:
                    times.setdefault(m, []).append(pro)
                m += SLOT_STEP_MINUTES
    return dict(sorted(times.items()))


def days_with_slots(salon, service, professional=None, now=None):
    """[(jour, nombre de créneaux)] sur la période réservable."""
    now = now or local_now()
    return [(day, len(available_times(salon, service, day, professional, now))) for day in booking_days(now)]


# --- Réserver / annuler ------------------------------------------------------

def create_booking(*, salon, service, professional, day, start, client_name, client_phone,
                   client_email="", note="", now=None) -> Booking:
    """Vérifie de nouveau le créneau (il a pu être pris entre-temps) puis l'enregistre."""
    if service.salon_id != salon.pk or (professional and professional.salon_id != salon.pk):
        raise BookingError("Cette prestation ou ce coiffeur n'appartient pas au salon.")

    with transaction.atomic():
        # Une réservation à la fois par salon : évite que deux clients prennent le même créneau
        salon = Salon.objects.select_for_update().get(pk=salon.pk)

        key = phone_key(client_phone)
        upcoming = _confirmed(salon.bookings.filter(date__gte=(now or local_now()).date()))
        if sum(1 for p in upcoming.values_list("client_phone", flat=True) if phone_key(p) == key) >= MAX_ACTIVE_BOOKINGS_PER_PHONE:
            raise BookingError(
                f"Vous avez déjà {MAX_ACTIVE_BOOKINGS_PER_PHONE} réservations à venir dans ce salon. "
                "Annulez-en une ou contactez le salon."
            )

        free = available_times(salon, service, day, professional, now).get(_minutes(start))
        if not free:
            raise BookingError("Ce créneau n'est plus disponible. Choisissez une autre heure.")

        if professional is None:
            # « Peu importe » : le coiffeur le moins chargé ce jour-là
            load = {p.pk: 0 for p in free}
            for pro_id in _confirmed(salon.bookings.filter(date=day)).values_list("professional_id", flat=True):
                if pro_id in load:
                    load[pro_id] += 1
            professional = min(free, key=lambda p: (load[p.pk], p.display_name))

        return Booking.objects.create(
            salon=salon, professional=professional, service=service,
            service_name=service.name, price=service.price, duration_minutes=service.duration_minutes,
            date=day, start_time=start, end_time=_time(_minutes(start) + service.blocked_minutes),
            client_name=client_name.strip(), client_phone=client_phone.strip(),
            client_email=client_email.strip(), note=note.strip(),
        )


def find_booking(code, phone):
    """Réservation correspondant au code ET au téléphone (le code seul ne suffit pas)."""
    booking = Booking.objects.select_related("salon", "professional").filter(code=normalize_code(code)).first()
    if booking and phone_key(phone) and phone_key(booking.client_phone) == phone_key(phone):
        return booking
    return None


def can_cancel(booking, now=None) -> bool:
    return booking.status == Booking.Status.CONFIRMED and starts_at(booking) > (now or local_now())


def cancel_booking(booking, now=None) -> None:
    if not can_cancel(booking, now):
        raise BookingError("Cette réservation ne peut plus être annulée.")
    booking.status = Booking.Status.CANCELLED_BY_CLIENT
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at", "updated_at"])
