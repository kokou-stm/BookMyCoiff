

from datetime import date as date_type, time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Weekday(models.IntegerChoices):
    # Même numérotation que date.weekday() : lundi = 0
    MONDAY = 0, "Lundi"
    TUESDAY = 1, "Mardi"
    WEDNESDAY = 2, "Mercredi"
    THURSDAY = 3, "Jeudi"
    FRIDAY = 4, "Vendredi"
    SATURDAY = 5, "Samedi"
    SUNDAY = 6, "Dimanche"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TimeRangeMixin(models.Model):
    """Plage horaire start_time < end_time sur une même journée."""

    start_time = models.TimeField("début")
    end_time = models.TimeField("fin")

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "L'heure de fin doit être après l'heure de début."})


# ---------------------------------------------------------------------------
# Bloc 1 : fiche salon, professionnels, catalogue
# ---------------------------------------------------------------------------


class Salon(TimestampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_salons",
        verbose_name="gérant",
    )
    name = models.CharField("nom", max_length=150)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    # Photo affichée sur la carte du salon (liste) et en tête de sa fiche
    cover_photo = models.ImageField("photo de couverture", upload_to="salons/covers/", blank=True)

    # Contact (le client peut appeler / écrire avant de se déplacer)
    phone = models.CharField("téléphone", max_length=30)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    # Localisation (recherche du salon le plus proche + distance)
    address = models.CharField("adresse", max_length=255)
    city = models.CharField("ville", max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    # Note de base attribuée par la plateforme (distincte des notes clients)
    base_rating = models.DecimalField(
        "note de base",
        max_digits=2,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )

    # Capacité : nombre de postes opérationnels
    workstation_count = models.PositiveSmallIntegerField("nombre de postes", default=1)

    offers_home_service = models.BooleanField("propose des services à domicile", default=False)

    # Flag ouvert/fermé actionnable par le gérant (coupe toutes les réservations)
    is_accepting_bookings = models.BooleanField("accepte les réservations", default=True)
    # Visibilité sur la plateforme. Publié dès l'inscription pour l'instant ; l'équipe peut le masquer depuis l'admin.
    # (La validation manuelle avec e-mails viendra plus tard.)
    is_published = models.BooleanField("publié", default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["city"]), models.Index(fields=["latitude", "longitude"])]

    def __str__(self):
        return self.name

    @property
    def cover_image(self):
        """Photo de couverture, ou à défaut la première photo « cadre » du salon."""
        if self.cover_photo:
            return self.cover_photo
        photo = next((p for p in self.photos.all() if p.kind == SalonPhoto.Kind.SETTING), None)
        return photo.image if photo else None

    def opening_ranges_for(self, day: date_type) -> list[tuple[time, time]]:
        return [
            (h.start_time, h.end_time)
            for h in self.opening_hours.filter(weekday=day.weekday()).order_by("start_time")
        ]


class SalonPhoto(TimestampedModel):
    class Kind(models.TextChoices):
        SETTING = "setting", "Cadre"
        WORK = "work", "Réalisation"

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="salons/%Y/%m/")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SETTING)
    caption = models.CharField("légende", max_length=200, blank=True)
    # Optionnel : rattacher une réalisation à un service et/ou à un pro
    service = models.ForeignKey(
        "Service", on_delete=models.SET_NULL, null=True, blank=True, related_name="photos"
    )
    professional = models.ForeignKey(
        "Professional", on_delete=models.SET_NULL, null=True, blank=True, related_name="photos"
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.salon} — {self.get_kind_display()} #{self.pk}"


class Equipment(models.Model):
    """Outillage / équipements du salon."""

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="equipment")
    name = models.CharField("nom", max_length=120)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "équipement"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["salon", "name"], name="unique_equipment_per_salon")
        ]

    def __str__(self):
        return self.name


class Professional(TimestampedModel):
    """Coiffeur / barbier, toujours rattaché à un salon."""

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="professionals")
    # Compte de connexion du pro (facultatif : le gérant peut créer le profil avant)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="professional_profile",
    )
    display_name = models.CharField("nom affiché", max_length=100)
    photo = models.ImageField(upload_to="professionals/", blank=True)
    bio = models.TextField(blank=True)
    qualifications = models.TextField(
        blank=True, help_text="Diplômes, formations, spécialités (une par ligne)."
    )
    years_of_experience = models.PositiveSmallIntegerField("années d'expérience", default=0)
    services = models.ManyToManyField(
        "Service", related_name="professionals", blank=True, verbose_name="services réalisés"
    )

    is_active = models.BooleanField("actif", default=True)
    # Flag ouvert/fermé actionnable par le barbier lui-même
    is_accepting_bookings = models.BooleanField("accepte les réservations", default=True)

    class Meta:
        verbose_name = "professionnel"
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.salon})"

    def base_ranges_for(self, day: date_type) -> list[tuple[time, time]]:
        own = [
            (h.start_time, h.end_time)
            for h in self.working_hours.filter(weekday=day.weekday()).order_by("start_time")
        ]
        return own if own else self.salon.opening_ranges_for(day)

    def availability_for(self, day: date_type) -> list[tuple[time, time]]:
        """Plages réservables du pro pour `day`, triées et fusionnées."""
        if not (self.is_active and self.is_accepting_bookings and self.salon.is_accepting_bookings):
            return []

        overrides = list(self.overrides.filter(date=day))
        if any(o.kind == AvailabilityOverride.Kind.CLOSED and o.is_full_day for o in overrides):
            return []

        ranges = self.base_ranges_for(day) + [
            (o.start_time, o.end_time) for o in overrides if o.kind == AvailabilityOverride.Kind.OPEN
        ]
        ranges = _merge(ranges)
        for o in overrides:
            if o.kind == AvailabilityOverride.Kind.CLOSED:
                ranges = _subtract(ranges, (o.start_time, o.end_time))
        return ranges


class Service(TimestampedModel):
    class Category(models.TextChoices):
        HAIRCUT = "haircut", "Coupe"
        BEARD = "beard", "Barbe"
        BRAIDS = "braids", "Tresses / nattes"
        COLOR = "color", "Coloration"
        CARE = "care", "Soin"
        STYLING = "styling", "Coiffage"
        OTHER = "other", "Autre"

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="services")
    name = models.CharField("nom", max_length=120)
    category = models.CharField(
        "catégorie", max_length=20, choices=Category.choices, default=Category.HAIRCUT
    )
    description = models.TextField(blank=True)
    price = models.DecimalField("prix", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    # Durée fixée par le barbier + marge pour les imprévus
    duration_minutes = models.PositiveSmallIntegerField(
        "durée (min)", validators=[MinValueValidator(5)]
    )
    buffer_minutes = models.PositiveSmallIntegerField(
        "marge (min)", default=0, help_text="Temps tampon ajouté après la prestation."
    )
    available_at_home = models.BooleanField("disponible à domicile", default=False)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(fields=["salon", "name"], name="unique_service_per_salon")
        ]

    def __str__(self):
        return f"{self.name} — {self.salon}"

    @property
    def blocked_minutes(self) -> int:
        """Temps total à bloquer dans l'agenda pour ce service."""
        return self.duration_minutes + self.buffer_minutes

    def clean(self):
        super().clean()
        if self.available_at_home and self.salon_id and not self.salon.offers_home_service:
            raise ValidationError(
                {"available_at_home": "Le salon ne propose pas de services à domicile."}
            )


# ---------------------------------------------------------------------------
# Bloc 2 : disponibilités
# ---------------------------------------------------------------------------


class OpeningHours(TimeRangeMixin):
    """Horaires habituels du salon. Plusieurs plages par jour possibles (pause midi)."""

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="opening_hours")
    weekday = models.PositiveSmallIntegerField("jour", choices=Weekday.choices)

    class Meta:
        verbose_name = "horaire d'ouverture"
        verbose_name_plural = "horaires d'ouverture"
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")), name="opening_hours_end_after_start"
            )
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class WorkingHours(TimeRangeMixin):
    """Horaires habituels d'un pro. S'il n'en a aucun pour un jour, ceux du salon s'appliquent."""

    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="working_hours"
    )
    weekday = models.PositiveSmallIntegerField("jour", choices=Weekday.choices)

    class Meta:
        verbose_name = "horaire de travail"
        verbose_name_plural = "horaires de travail"
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")), name="working_hours_end_after_start"
            )
        ]

    def __str__(self):
        return f"{self.professional.display_name} — {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class AvailabilityOverride(TimestampedModel):
    """
    Ajustement ponctuel réglé par le barbier (typiquement le matin même) :
    - CLOSED sans heures  : absent toute la journée
    - CLOSED avec heures  : indisponible sur cette plage
    - OPEN avec heures    : plage supplémentaire (ex. ouverture tôt, heures creuses)
    """

    class Kind(models.TextChoices):
        OPEN = "open", "Ouvert"
        CLOSED = "closed", "Fermé"

    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="overrides"
    )
    date = models.DateField()
    kind = models.CharField("type", max_length=10, choices=Kind.choices)
    start_time = models.TimeField("début", null=True, blank=True)
    end_time = models.TimeField("fin", null=True, blank=True)
    reason = models.CharField("motif", max_length=200, blank=True)

    class Meta:
        verbose_name = "ajustement de disponibilité"
        verbose_name_plural = "ajustements de disponibilité"
        ordering = ["date", "start_time"]
        indexes = [models.Index(fields=["professional", "date"])]
        constraints = [
            # soit les deux heures, soit aucune
            models.CheckConstraint(
                condition=Q(start_time__isnull=True, end_time__isnull=True)
                | Q(start_time__isnull=False, end_time__isnull=False, end_time__gt=F("start_time")),
                name="override_valid_time_range",
            ),
            # une ouverture exceptionnelle doit préciser ses heures
            models.CheckConstraint(
                condition=~Q(kind="open") | Q(start_time__isnull=False),
                name="override_open_requires_times",
            ),
        ]

    def __str__(self):
        when = "toute la journée" if self.is_full_day else f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"
        return f"{self.professional.display_name} — {self.date} — {self.get_kind_display()} {when}"

    @property
    def is_full_day(self) -> bool:
        return self.start_time is None and self.end_time is None

    def clean(self):
        super().clean()
        if (self.start_time is None) != (self.end_time is None):
            raise ValidationError("Renseignez les deux heures, ou aucune pour toute la journée.")
        if self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "L'heure de fin doit être après l'heure de début."})
        if self.kind == self.Kind.OPEN and self.is_full_day:
            raise ValidationError("Une ouverture exceptionnelle doit avoir des heures.")


# ---------------------------------------------------------------------------
# Utilitaires de calcul de plages
# ---------------------------------------------------------------------------


def _merge(ranges: list[tuple[time, time]]) -> list[tuple[time, time]]:
    merged: list[tuple[time, time]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(ranges: list[tuple[time, time]], cut: tuple[time, time]) -> list[tuple[time, time]]:
    cut_start, cut_end = cut
    result = []
    for start, end in ranges:
        if cut_end <= start or cut_start >= end:
            result.append((start, end))
            continue
        if start < cut_start:
            result.append((start, cut_start))
        if cut_end < end:
            result.append((cut_end, end))
    return result
