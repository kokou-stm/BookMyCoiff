from datetime import date, time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import AvailabilityOverride, OpeningHours, Professional, Salon, Service, WorkingHours

MONDAY = date(2026, 11, 23)  # un lundi


class AvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = get_user_model().objects.create_user("gerant")
        cls.salon = Salon.objects.create(
            owner=owner, name="Salon Test", slug="salon-test", phone="000",
            address="1 rue X", city="Lomé", latitude=6.13, longitude=1.22,
        )
        # Lundi 9h-12h et 14h-19h (pause midi)
        OpeningHours.objects.create(salon=cls.salon, weekday=0, start_time=time(9), end_time=time(12))
        OpeningHours.objects.create(salon=cls.salon, weekday=0, start_time=time(14), end_time=time(19))
        cls.pro = Professional.objects.create(salon=cls.salon, display_name="Koffi")

    def test_falls_back_to_salon_hours(self):
        self.assertEqual(
            self.pro.availability_for(MONDAY),
            [(time(9), time(12)), (time(14), time(19))],
        )

    def test_closed_on_day_without_hours(self):
        self.assertEqual(self.pro.availability_for(date(2026, 11, 24)), [])  # mardi

    def test_own_working_hours_replace_salon_hours(self):
        WorkingHours.objects.create(professional=self.pro, weekday=0, start_time=time(10), end_time=time(16))
        self.assertEqual(self.pro.availability_for(MONDAY), [(time(10), time(16))])

    def test_morning_adjustments(self):
        # Le barbier ajoute 12h-14h (heures creuses) et bloque 16h-17h
        AvailabilityOverride.objects.create(
            professional=self.pro, date=MONDAY, kind="open", start_time=time(12), end_time=time(14)
        )
        AvailabilityOverride.objects.create(
            professional=self.pro, date=MONDAY, kind="closed", start_time=time(16), end_time=time(17)
        )
        self.assertEqual(
            self.pro.availability_for(MONDAY),
            [(time(9), time(16)), (time(17), time(19))],
        )

    def test_full_day_closed(self):
        AvailabilityOverride.objects.create(professional=self.pro, date=MONDAY, kind="closed")
        self.assertEqual(self.pro.availability_for(MONDAY), [])

    def test_flags_disable_bookings(self):
        self.pro.is_accepting_bookings = False
        self.assertEqual(self.pro.availability_for(MONDAY), [])
        self.pro.is_accepting_bookings = True
        self.salon.is_accepting_bookings = False
        self.assertEqual(self.pro.availability_for(MONDAY), [])

    def test_db_rejects_invalid_override(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AvailabilityOverride.objects.create(professional=self.pro, date=MONDAY, kind="open")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AvailabilityOverride.objects.create(
                professional=self.pro, date=MONDAY, kind="closed", start_time=time(15), end_time=time(14)
            )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def make_salon(owner, slug, lat=6.13, lng=1.22, published=True):
    return Salon.objects.create(
        owner=owner, name=slug.title(), slug=slug, phone="000", address="rue",
        city="Lomé", latitude=lat, longitude=lng, is_published=published,
    )


class PublicApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        owner = get_user_model().objects.create_user("gerant")
        cls.near = make_salon(owner, "proche", 6.13, 1.22)
        cls.far = make_salon(owner, "loin", 6.30, 1.40)
        make_salon(owner, "cache", published=False)
        OpeningHours.objects.create(salon=cls.near, weekday=0, start_time=time(9), end_time=time(12))
        Service.objects.create(salon=cls.near, name="Coupe", price=2000, duration_minutes=30)
        cls.pro = Professional.objects.create(salon=cls.near, display_name="Koffi")

    def test_list_only_published_sorted_by_distance(self):
        r = self.client.get("/api/salons/", {"lat": 6.13, "lng": 1.22})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["slug"] for s in r.data["results"]], ["proche", "loin"])
        self.assertEqual(r.data["results"][0]["distance_km"], 0)

    def test_radius_filter(self):
        r = self.client.get("/api/salons/", {"lat": 6.13, "lng": 1.22, "radius_km": 5})
        self.assertEqual([s["slug"] for s in r.data["results"]], ["proche"])

    def test_detail(self):
        r = self.client.get("/api/salons/proche/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["services"][0]["blocked_minutes"], 30)
        self.assertEqual(r.data["professionals"][0]["display_name"], "Koffi")
        self.assertEqual(self.client.get("/api/salons/cache/").status_code, 404)

    def test_availability(self):
        r = self.client.get(f"/api/professionals/{self.pro.id}/availability/", {"date": "2026-11-23", "days": 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["days"][0]["ranges"], [{"start": "09:00", "end": "12:00"}])
        self.assertEqual(r.data["days"][1]["ranges"], [])
        bad = self.client.get(f"/api/professionals/{self.pro.id}/availability/", {"days": 99})
        self.assertEqual(bad.status_code, 400)


class ManageApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user("gerant")
        cls.other = User.objects.create_user("autre")
        cls.barber = User.objects.create_user("barbier")
        cls.salon = make_salon(cls.owner, "mon-salon")
        cls.other_salon = make_salon(cls.other, "autre-salon")
        cls.pro = Professional.objects.create(salon=cls.salon, display_name="Koffi", user=cls.barber)
        cls.other_service = Service.objects.create(
            salon=cls.other_salon, name="Coupe", price=1000, duration_minutes=20
        )

    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/manage/salons/").status_code, 403)

    def test_create_salon_sets_owner_and_ignores_platform_fields(self):
        self.client.force_authenticate(self.other)
        r = self.client.post("/api/manage/salons/", {
            "name": "Neuf", "slug": "neuf", "phone": "1", "address": "a", "city": "Lomé",
            "latitude": "6.1", "longitude": "1.2", "is_published": True, "base_rating": "5.0",
        })
        self.assertEqual(r.status_code, 201, r.data)
        salon = Salon.objects.get(slug="neuf")
        self.assertEqual(salon.owner, self.other)
        self.assertFalse(salon.is_published)
        self.assertIsNone(salon.base_rating)

    def test_owner_sees_only_own_salons(self):
        self.client.force_authenticate(self.owner)
        r = self.client.get("/api/manage/salons/")
        self.assertEqual([s["slug"] for s in r.data["results"]], ["mon-salon"])

    def test_cannot_add_service_to_someone_else_salon(self):
        self.client.force_authenticate(self.owner)
        r = self.client.post("/api/manage/services/", {
            "salon": self.other_salon.id, "name": "X", "price": 10, "duration_minutes": 15,
        })
        self.assertEqual(r.status_code, 400)

    def test_home_service_rule_applied(self):
        self.client.force_authenticate(self.owner)
        r = self.client.post("/api/manage/services/", {
            "salon": self.salon.id, "name": "Domicile", "price": 10, "duration_minutes": 15,
            "available_at_home": True,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("available_at_home", r.data)

    def test_professional_services_must_belong_to_salon(self):
        self.client.force_authenticate(self.owner)
        r = self.client.patch(
            f"/api/manage/professionals/{self.pro.id}/", {"services": [self.other_service.id]}, format="json"
        )
        self.assertEqual(r.status_code, 400)

    def test_barber_manages_own_profile_but_cannot_delete(self):
        self.client.force_authenticate(self.barber)
        r = self.client.post(f"/api/manage/professionals/{self.pro.id}/toggle_bookings/")
        self.assertEqual(r.data, {"is_accepting_bookings": False})
        r = self.client.patch(f"/api/manage/professionals/{self.pro.id}/", {"bio": "Expert dégradés", "is_active": False})
        self.assertEqual(r.status_code, 200)
        self.pro.refresh_from_db()
        self.assertEqual(self.pro.bio, "Expert dégradés")
        self.assertTrue(self.pro.is_active)  # réservé au gérant
        self.assertEqual(self.client.delete(f"/api/manage/professionals/{self.pro.id}/").status_code, 403)

    def test_barber_sets_morning_override(self):
        self.client.force_authenticate(self.barber)
        r = self.client.post("/api/manage/overrides/", {
            "professional": self.pro.id, "date": "2026-11-23", "kind": "closed", "reason": "malade",
        })
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post("/api/manage/overrides/", {
            "professional": self.pro.id, "date": "2026-11-23", "kind": "open",
        })
        self.assertEqual(r.status_code, 400)

    def test_stranger_cannot_touch_professional(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/manage/professionals/{self.pro.id}/").status_code, 404)
        r = self.client.post("/api/manage/overrides/", {
            "professional": self.pro.id, "date": "2026-11-23", "kind": "closed",
        })
        self.assertEqual(r.status_code, 400)


class HomePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = get_user_model().objects.create_user("gerant")
        cls.salon = make_salon(owner, "tresses-ama")
        Service.objects.create(salon=cls.salon, name="Nattes", category="braids", price=5000, duration_minutes=90)
        make_salon(owner, "coupe-yao", 6.2, 1.3)
        make_salon(owner, "invisible", published=False)

    def test_lists_published_salons(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tresses-Ama")
        self.assertContains(r, "Coupe-Yao")
        self.assertNotContains(r, "Invisible")
        self.assertContains(r, "À partir de")

    def test_category_filter(self):
        r = self.client.get("/", {"service_category": "braids"})
        self.assertContains(r, "Tresses-Ama")
        self.assertNotContains(r, "Coupe-Yao")

    def test_geolocation_sorts_and_bad_coordinates_are_ignored(self):
        r = self.client.get("/", {"lat": 6.2, "lng": 1.3})
        self.assertEqual([s.slug for s in r.context["page"].object_list], ["coupe-yao", "tresses-ama"])
        self.assertContains(r, " km")
        r = self.client.get("/", {"lat": "abc", "lng": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page"].paginator.count, 2)


    def test_what_and_where_search(self):
        r = self.client.get("/", {"search": "natt"})  # nom de service
        self.assertEqual([s.slug for s in r.context["page"].object_list], ["tresses-ama"])
        r = self.client.get("/", {"where": "lom"})
        self.assertEqual(r.context["page"].paginator.count, 2)
        r = self.client.get("/", {"where": "Paris"})
        self.assertEqual(r.context["page"].paginator.count, 0)

    def test_service_tiles_toggle_filter(self):
        r = self.client.get("/", {"service_category": "braids", "where": "lom"})
        tiles = {t["key"]: t for t in r.context["service_tiles"]}
        self.assertTrue(tiles["braids"]["active"])
        self.assertNotIn("service_category", tiles["braids"]["url"])  # re-clic = retirer le filtre
        self.assertIn("where=lom", tiles["braids"]["url"])
        self.assertIn("service_category=beard", tiles["beard"]["url"])

    def test_quick_filters(self):
        Salon.objects.filter(slug="tresses-ama").update(base_rating=4.5)
        Salon.objects.filter(slug="coupe-yao").update(base_rating=3.5, is_accepting_bookings=False)
        r = self.client.get("/", {"min_rating": 4})
        self.assertEqual([s.slug for s in r.context["page"].object_list], ["tresses-ama"])
        r = self.client.get("/", {"open": "true"})
        self.assertEqual([s.slug for s in r.context["page"].object_list], ["tresses-ama"])
        r = self.client.get("/", {"min_rating": "x"})  # ignoré, pas d'erreur
        self.assertEqual(r.context["page"].paginator.count, 2)
        self.assertContains(r, 'name="min_rating"')

    def test_active_filters_count(self):
        r = self.client.get("/", {"service_category": "braids", "open": "true", "search": "x"})
        self.assertEqual(r.context["active_filters"], 2)
        self.assertContains(r, 'class="filters-count">2<')

class CoverPhotoTests(TestCase):
    def test_cover_photo_wins_over_gallery_and_falls_back(self):
        owner = get_user_model().objects.create_user("gerant")
        salon = make_salon(owner, "cover")
        self.assertIsNone(salon.cover_image)
        salon.photos.create(image="salons/cadre.jpg", kind="setting")
        salon.photos.create(image="salons/coupe.jpg", kind="work", position=0)
        self.assertEqual(Salon.objects.get(pk=salon.pk).cover_image.name, "salons/cadre.jpg")
        salon.cover_photo = "salons/covers/facade.jpg"
        salon.save()
        self.assertEqual(Salon.objects.get(pk=salon.pk).cover_image.name, "salons/covers/facade.jpg")
        r = self.client.get("/")
        self.assertContains(r, "/media/salons/covers/facade.jpg")
        r = self.client.get("/api/salons/cover/")
        self.assertTrue(r.data["cover_photo"].endswith("/media/salons/covers/facade.jpg"))



class SalonRegisterTests(TestCase):
    URL = "/inscrire-mon-salon/"

    def salon_data(self, **extra):
        data = {
            "name": "Coupe Royale", "phone": "+228 90 11 22 33", "address": "5 rue des Palmiers",
            "city": "Lomé", "latitude": "6.130000", "longitude": "1.220000", "workstation_count": "2",
            "owner_is_pro": "on",
            # lundi ouvert 9h-18h, les autres jours fermés
            "day0_open": "on", "day0_start": "09:00", "day0_end": "18:00",
        }
        data.update(extra)
        return data

    def account_data(self, **extra):
        data = {
            "account-first_name": "Kossi", "account-last_name": "Mensah", "account-email": "Kossi@Example.com",
            "account-password1": "coupe-royale-2026", "account-password2": "coupe-royale-2026",
        }
        data.update(extra)
        return data

    def test_page_is_public(self):
        response = self.client.get(self.URL)
        self.assertContains(response, "Votre compte")
        self.assertContains(response, "Horaires d'ouverture")

    def test_new_owner_creates_account_and_salon(self):
        response = self.client.post(self.URL, {**self.salon_data(), **self.account_data()})
        self.assertRedirects(response, "/mes-salons/")

        user = get_user_model().objects.get(username="kossi@example.com")
        self.assertTrue(user.check_password("coupe-royale-2026"))
        salon = Salon.objects.get(owner=user)
        self.assertEqual(salon.slug, "coupe-royale")
        self.assertFalse(salon.is_published)  # en attente de validation
        self.assertEqual(list(salon.opening_hours.values_list("weekday", "start_time", "end_time")),
                         [(0, time(9), time(18))])
        self.assertEqual(salon.professionals.get().user, user)
        # Connecté automatiquement
        self.assertContains(self.client.get("/mes-salons/"), "En attente de validation")

    def test_logged_in_owner_skips_account(self):
        owner = get_user_model().objects.create_user("gerant", password="x")
        Salon.objects.create(owner=owner, name="Coupe Royale", slug="coupe-royale", phone="0",
                             address="a", city="Lomé", latitude=6.1, longitude=1.2)
        self.client.force_login(owner)
        self.assertNotContains(self.client.get(self.URL), "Votre compte")

        response = self.client.post(self.URL, self.salon_data(owner_is_pro=""))
        self.assertRedirects(response, "/mes-salons/")
        salon = Salon.objects.exclude(slug="coupe-royale").get()
        self.assertEqual(salon.slug, "coupe-royale-2")  # slug unique
        self.assertEqual(salon.owner, owner)
        self.assertFalse(salon.professionals.exists())

    def test_errors_create_nothing(self):
        get_user_model().objects.create_user("kossi@example.com")
        data = {
            **self.salon_data(latitude="", longitude="", day0_end="08:00"),
            **self.account_data(**{"account-password2": "autre"}),
        }
        response = self.client.post(self.URL, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Placez votre salon sur la carte.")
        self.assertContains(response, "la fermeture doit être après l")
        self.assertContains(response, "Un compte existe déjà")
        self.assertFalse(Salon.objects.exists())

    def test_requires_one_open_day(self):
        data = self.salon_data(day0_open="")
        self.client.force_login(get_user_model().objects.create_user("gerant"))
        self.assertContains(self.client.post(self.URL, data), "au moins un jour d")
        self.assertFalse(Salon.objects.exists())

    def test_login_with_email_and_my_salons_requires_login(self):
        self.assertRedirects(self.client.get("/mes-salons/"), "/connexion/?next=/mes-salons/")
        get_user_model().objects.create_user("kossi@example.com", password="coupe-royale-2026")
        response = self.client.post("/connexion/", {"username": "Kossi@example.com", "password": "coupe-royale-2026"})
        self.assertRedirects(response, "/mes-salons/")

    def test_home_links_to_register_page(self):
        self.assertContains(self.client.get("/"), 'href="/inscrire-mon-salon/"')
