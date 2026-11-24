"""
Données de démonstration pour voir la page d'accueil remplie.

    venv/bin/python manage.py seed_demo           # crée (ou met à jour) 3 salons fictifs
    venv/bin/python manage.py seed_demo --delete  # supprime ces données
"""

from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from barbershopApp.models import Equipment, OpeningHours, Professional, Salon, Service

DEMO_USERNAME = "demo_gerant"

SALONS = [
    {
        "slug": "demo-le-fade-studio", "name": "Le Fade Studio", "address": "12 avenue de la Paix",
        "lat": 6.1319, "lng": 1.2228, "rating": "4.7", "home": True, "stations": 4,
        "description": "Spécialistes des dégradés et du taillage de barbe, dans un cadre climatisé.",
        "services": [
            ("Coupe homme", "haircut", 2500, 30, 5), ("Dégradé + contours", "haircut", 3500, 45, 5),
            ("Taille de barbe", "beard", 1500, 20, 5), ("Soin barbe à la serviette chaude", "care", 2500, 30, 5),
        ],
        "pros": [("Koffi", 8), ("Yao", 3)],
        "equipment": ["Tondeuses professionnelles", "Serviettes chaudes", "Climatisation", "Stérilisateur UV"],
    },
    {
        "slug": "demo-maison-tresses", "name": "Maison des Tresses", "address": "45 rue du Marché",
        "lat": 6.1405, "lng": 1.2150, "rating": "4.9", "home": True, "stations": 6,
        "description": "Tresses, nattes et coiffures protectrices. Mèches disponibles sur place.",
        "services": [
            ("Nattes collées", "braids", 5000, 90, 10), ("Box braids", "braids", 15000, 240, 15),
            ("Shampoing + soin", "care", 3000, 40, 5), ("Coloration", "color", 8000, 90, 10),
        ],
        "pros": [("Akossiwa", 12), ("Mawuena", 5), ("Ama", 2)],
        "equipment": ["Casques séchoirs", "Bacs à shampoing", "Wi-Fi"],
    },
    {
        "slug": "demo-barber-corner", "name": "Barber Corner", "address": "3 boulevard du Mono",
        "lat": 6.1720, "lng": 1.2400, "rating": None, "home": False, "stations": 2,
        "description": "Petit salon de quartier, rapide et sans chichi.",
        "services": [("Coupe homme", "haircut", 1500, 25, 5), ("Rasage complet", "beard", 1000, 15, 5)],
        "pros": [("Edem", 4)],
        "equipment": ["Tondeuses", "Rasoirs à lame"],
    },
    {
        "slug": "demo-afro-beaute", "name": "Afro Beauté Lounge", "address": "27 rue des Cocotiers",
        "lat": 6.1250, "lng": 1.2050, "rating": "4.5", "home": True, "stations": 5,
        "description": "Soins capillaires naturels, défrisage, tissages et coiffures de cérémonie.",
        "services": [
            ("Tissage", "styling", 10000, 120, 10), ("Défrisage", "care", 6000, 60, 10),
            ("Soin hydratant cheveux naturels", "care", 4000, 45, 5), ("Chignon de cérémonie", "styling", 7000, 75, 10),
        ],
        "pros": [("Essi", 9), ("Dzifa", 4)],
        "equipment": ["Vapeur capillaire", "Casques séchoirs", "Produits naturels", "Climatisation"],
    },
    {
        "slug": "demo-gentleman-barber", "name": "Gentleman Barber", "address": "8 avenue du Golfe",
        "lat": 6.1580, "lng": 1.2600, "rating": "4.2", "home": False, "stations": 3,
        "description": "Barbier à l'ancienne : rasage au coupe-chou, soins du visage, ambiance lounge.",
        "services": [
            ("Coupe classique", "haircut", 3000, 35, 5), ("Rasage au coupe-chou", "beard", 2500, 30, 5),
            ("Coupe + barbe", "haircut", 5000, 60, 5), ("Coloration barbe", "color", 3000, 30, 5),
        ],
        "pros": [("Sénamé", 15), ("Kodjo", 6)],
        "equipment": ["Coupe-chou", "Fauteuils barbier vintage", "Serviettes chaudes", "Wi-Fi"],
    },
]


class Command(BaseCommand):
    help = "Crée des salons de démonstration (fictifs) pour visualiser la page d'accueil."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Supprime les données de démo.")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["delete"]:
            Salon.objects.filter(slug__startswith="demo-").delete()
            User.objects.filter(username=DEMO_USERNAME).delete()
            self.stdout.write(self.style.SUCCESS("Données de démo supprimées."))
            return

        owner, created = User.objects.get_or_create(username=DEMO_USERNAME)
        if created:
            owner.set_unusable_password()
            owner.save()

        for data in SALONS:
            salon, _ = Salon.objects.update_or_create(slug=data["slug"], defaults={
                "owner": owner, "name": data["name"], "description": data["description"],
                "phone": "+228 90 00 00 00", "whatsapp": "+228 90 00 00 00",
                "address": data["address"], "city": "Lomé",
                "latitude": data["lat"], "longitude": data["lng"], "base_rating": data["rating"],
                "workstation_count": data["stations"], "offers_home_service": data["home"],
                "is_published": True, "is_accepting_bookings": True,
            })
            salon.opening_hours.all().delete()
            for weekday in range(6):  # lundi → samedi, pause midi
                OpeningHours.objects.create(salon=salon, weekday=weekday, start_time=time(8), end_time=time(13))
                OpeningHours.objects.create(salon=salon, weekday=weekday, start_time=time(14), end_time=time(20))

            services = []
            for name, category, price, duration, buffer in data["services"]:
                service, _ = Service.objects.update_or_create(salon=salon, name=name, defaults={
                    "category": category, "price": price, "duration_minutes": duration,
                    "buffer_minutes": buffer, "available_at_home": data["home"],
                })
                services.append(service)

            for name, years in data["pros"]:
                pro, _ = Professional.objects.update_or_create(
                    salon=salon, display_name=name, defaults={"years_of_experience": years}
                )
                pro.services.set(services)

            for name in data["equipment"]:
                Equipment.objects.get_or_create(salon=salon, name=name)

        self.stdout.write(self.style.SUCCESS(f"{len(SALONS)} salons de démo prêts. Ouvrez http://127.0.0.1:8000/"))
