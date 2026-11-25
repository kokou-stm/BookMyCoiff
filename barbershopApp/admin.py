from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

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


class OpeningHoursInline(admin.TabularInline):
    model = OpeningHours
    extra = 0


class EquipmentInline(admin.TabularInline):
    model = Equipment
    extra = 0


class SalonPhotoInline(admin.TabularInline):
    model = SalonPhoto
    extra = 0
    fields = ("image", "kind", "caption", "service", "professional", "position")


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0
    fields = ("name", "category", "price", "duration_minutes", "buffer_minutes", "available_at_home", "is_active")


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "base_rating", "workstation_count", "is_accepting_bookings", "is_published")
    list_filter = ("city", "is_published", "is_accepting_bookings", "offers_home_service")
    list_editable = ("is_accepting_bookings",)
    search_fields = ("name", "address", "city")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("cover_preview",)
    inlines = [OpeningHoursInline, ServiceInline, EquipmentInline, SalonPhotoInline]

    @admin.display(description="aperçu de la couverture")
    def cover_preview(self, salon):
        if not salon.cover_photo:
            return "—"
        return format_html('<img src="{}" style="max-height:120px;border-radius:8px">', salon.cover_photo.url)


class WorkingHoursInline(admin.TabularInline):
    model = WorkingHours
    extra = 0


class AvailabilityOverrideInline(admin.TabularInline):
    model = AvailabilityOverride
    extra = 0


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ("display_name", "salon", "years_of_experience", "is_active", "is_accepting_bookings")
    list_filter = ("salon", "is_active", "is_accepting_bookings")
    list_editable = ("is_accepting_bookings",)
    search_fields = ("display_name", "salon__name")
    filter_horizontal = ("services",)
    inlines = [WorkingHoursInline, AvailabilityOverrideInline]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "salon", "category", "price", "duration_minutes", "buffer_minutes", "is_active")
    list_filter = ("category", "salon", "is_active", "available_at_home")
    search_fields = ("name", "salon__name")


@admin.register(AvailabilityOverride)
class AvailabilityOverrideAdmin(admin.ModelAdmin):
    list_display = ("professional", "date", "kind", "start_time", "end_time", "reason")
    list_filter = ("kind", "date", "professional__salon")
    date_hierarchy = "date"


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("code", "date", "start_time", "salon", "professional", "service_name", "client_name", "client_phone", "status")
    list_filter = ("status", "date", "salon")
    search_fields = ("code", "client_name", "client_phone", "client_email", "salon__name")
    date_hierarchy = "date"
    readonly_fields = ("code", "created_at", "updated_at", "cancelled_at")
    actions = ["cancel_by_salon"]

    @admin.action(description="Annuler (au nom du salon)")
    def cancel_by_salon(self, request, queryset):
        count = queryset.filter(status=Booking.Status.CONFIRMED).update(
            status=Booking.Status.CANCELLED_BY_SALON, cancelled_at=timezone.now(), updated_at=timezone.now()
        )
        self.message_user(request, f"{count} réservation(s) annulée(s).", messages.SUCCESS)
