from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

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


class ModelCleanMixin:
    """Exécute Model.clean() pour que l'API applique les mêmes règles que l'admin."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        instance = self.instance or model()
        m2m = {f.name for f in model._meta.many_to_many}
        for field, value in attrs.items():
            if field not in m2m:
                setattr(instance, field, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
            )
        return attrs


class OwnedSalonField(serializers.PrimaryKeyRelatedField):
    """Ne propose / n'accepte que les salons gérés par l'utilisateur connecté."""

    def get_queryset(self):
        return Salon.objects.filter(owner=self.context["request"].user)


class ManagedProfessionalField(serializers.PrimaryKeyRelatedField):
    """Pros du salon de l'utilisateur, ou son propre profil de pro."""

    def get_queryset(self):
        from .views import managed_professionals

        return managed_professionals(self.context["request"].user)


# ---------------------------------------------------------------------------
# Lecture publique (clients)
# ---------------------------------------------------------------------------


class OpeningHoursSerializer(ModelCleanMixin, serializers.ModelSerializer):
    salon = OwnedSalonField()
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = OpeningHours
        fields = ["id", "salon", "weekday", "weekday_display", "start_time", "end_time"]


class ServiceSerializer(ModelCleanMixin, serializers.ModelSerializer):
    salon = OwnedSalonField()
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    blocked_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Service
        fields = [
            "id", "salon", "name", "category", "category_display", "description", "price",
            "duration_minutes", "buffer_minutes", "blocked_minutes", "available_at_home", "is_active",
        ]


class EquipmentSerializer(serializers.ModelSerializer):
    salon = OwnedSalonField()

    class Meta:
        model = Equipment
        fields = ["id", "salon", "name", "description"]


class SalonPhotoSerializer(serializers.ModelSerializer):
    salon = OwnedSalonField()

    class Meta:
        model = SalonPhoto
        fields = ["id", "salon", "image", "kind", "caption", "service", "professional", "position"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        salon = attrs.get("salon", getattr(self.instance, "salon", None))
        for key in ("service", "professional"):
            obj = attrs.get(key)
            if obj and obj.salon_id != salon.id:
                raise serializers.ValidationError({key: "Doit appartenir au même salon."})
        return attrs


class ProfessionalSerializer(serializers.ModelSerializer):
    salon = OwnedSalonField()

    class Meta:
        model = Professional
        fields = [
            "id", "salon", "user", "display_name", "photo", "bio", "qualifications",
            "years_of_experience", "services", "is_active", "is_accepting_bookings",
        ]
        # Le lien avec un compte utilisateur se fait dans l'admin, par l'équipe
        read_only_fields = ["user"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        # Un pro qui édite son propre profil (sans être gérant) ne peut pas changer de salon
        if isinstance(self.instance, Professional) and request:
            if self.instance.salon.owner_id != request.user.id:
                for name in ("salon", "is_active"):
                    fields[name].read_only = True
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        salon = attrs.get("salon", getattr(self.instance, "salon", None))
        for service in attrs.get("services", []):
            if service.salon_id != salon.id:
                raise serializers.ValidationError(
                    {"services": f"« {service.name} » n'appartient pas à ce salon."}
                )
        return attrs


class PublicProfessionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Professional
        fields = [
            "id", "display_name", "photo", "bio", "qualifications",
            "years_of_experience", "services", "is_accepting_bookings",
        ]


class SalonSerializer(serializers.ModelSerializer):
    """Fiche salon éditable par le gérant (note de base et publication gérées par la plateforme)."""

    class Meta:
        model = Salon
        fields = [
            "id", "name", "slug", "description", "cover_photo", "phone", "whatsapp", "email",
            "address", "city", "latitude", "longitude", "base_rating", "workstation_count",
            "offers_home_service", "is_accepting_bookings", "is_published",
        ]
        read_only_fields = ["base_rating", "is_published"]


class SalonListSerializer(serializers.ModelSerializer):
    """Carte salon dans la liste (page d'accueil)."""

    cover_photo = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Salon
        fields = [
            "id", "name", "slug", "address", "city", "latitude", "longitude",
            "base_rating", "offers_home_service", "is_accepting_bookings",
            "cover_photo", "distance_km",
        ]

    def get_cover_photo(self, salon):
        image = salon.cover_image
        if not image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(image.url) if request else image.url

    def get_distance_km(self, salon):
        distance = getattr(salon, "distance_km", None)
        return round(distance, 2) if distance is not None else None


class SalonDetailSerializer(SalonListSerializer):
    """Fiche complète affichée quand le client ouvre un salon."""

    photos = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    equipment = serializers.SerializerMethodField()
    professionals = serializers.SerializerMethodField()
    opening_hours = serializers.SerializerMethodField()

    class Meta(SalonListSerializer.Meta):
        fields = SalonListSerializer.Meta.fields + [
            "description", "phone", "whatsapp", "email", "workstation_count",
            "photos", "services", "equipment", "professionals", "opening_hours",
        ]

    def _many(self, serializer_class, items, exclude=("salon",)):
        data = serializer_class(items, many=True, context=self.context).data
        return [{k: v for k, v in row.items() if k not in exclude} for row in data]

    def get_photos(self, salon):
        return self._many(SalonPhotoSerializer, salon.photos.all())

    def get_services(self, salon):
        return self._many(ServiceSerializer, [s for s in salon.services.all() if s.is_active])

    def get_equipment(self, salon):
        return self._many(EquipmentSerializer, salon.equipment.all())

    def get_professionals(self, salon):
        return PublicProfessionalSerializer(
            [p for p in salon.professionals.all() if p.is_active], many=True, context=self.context
        ).data

    def get_opening_hours(self, salon):
        return self._many(OpeningHoursSerializer, salon.opening_hours.all())


# ---------------------------------------------------------------------------
# Disponibilités (côté pro)
# ---------------------------------------------------------------------------


class WorkingHoursSerializer(ModelCleanMixin, serializers.ModelSerializer):
    professional = ManagedProfessionalField()
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = WorkingHours
        fields = ["id", "professional", "weekday", "weekday_display", "start_time", "end_time"]


class AvailabilityOverrideSerializer(ModelCleanMixin, serializers.ModelSerializer):
    professional = ManagedProfessionalField()

    class Meta:
        model = AvailabilityOverride
        fields = ["id", "professional", "date", "kind", "start_time", "end_time", "reason"]
