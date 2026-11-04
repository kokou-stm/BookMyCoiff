# BookMyCoiff
 
**Plateforme de réservation, de fidélisation clients et de vente d'articles pour la coiffure.**
 
BookMyCoiff est une plateforme web développée avec Django qui connecte les clients aux salons de coiffure et barbiers, facilite la réservation en ligne, améliore la fidélisation et permet la vente de produits professionnels.
 
---
 
## Description
 
BookMyCoiff répond aux besoins des clients (trouver le bon salon rapidement, réserver sans attente, gagner en confiance) et des prestataires (visibilité, gestion du temps et de la capacité, relation client et monétisation).
 
La plateforme propose :
- Recherche géolocalisée de salons
- Réservation de créneaux avec un professionnel spécifique
- Système de notation et d'avis
- Programme de fidélité et de parrainage
- Espace boutique pour produits de coiffure
- Interface complète pour les prestataires (salons et indépendants)
---
 
## Docs
Documentation word( en Brouillon) [Lien vers le doc](https://docs.google.com/document/d/1vaJXxq72N8pdWMHnOw1gvr8BpvN97334knPUoGiQbbg/edit?tab=t.0)

## Fonctionnalités principales
 
### Côté Client
- Recherche de salons proches avec géolocalisation, distance et notes (note de base + avis clients)
- Filtres rapides (budget, services, note, distance, etc.)
- Fiche salon complète :
  - Photos du cadre et des réalisations
  - Catalogue des services avec prix et durée
  - Liste des équipements
  - Professionnels et leurs notes individuelles
  - Témoignages clients
  - Créneaux disponibles par professionnel
- Réservation d'un créneau précis (avec un barbier préféré)
- Option services à domicile
- Chat ou contact direct avec le salon
- Programme de fidélité (points) et système de parrainage
- Avis et notations (salon + professionnel)
### Côté Prestataire (Salon & Indépendants)
- Visibilité accrue sur le marché local
- Gestion des horaires d'ouverture / fermeture
- Définition manuelle des créneaux disponibles chaque jour
- Attribution d'une durée précise à chaque service (+ marge d'incertitude)
- Gestion de la capacité (nombre de postes et de professionnels)
- Publication de promotions (notifiées aux clients)
- Suivi des avis et notes
- Outils de fidélisation (tarifs spéciaux, points de fidélité)
- Possibilité pour les indépendants (sans salon physique) de proposer leurs services (avec validation de profil)
### Espace Boutique
- Vente d'articles de coiffure (peignes, ciseaux, produits afro, etc.)
- Recommandations de produits aux clients
- Gestion des stocks et commandes (côté admin / prestataire)
### Fonctionnalités transverses
- Système de paiement (avec répartition commission plateforme / salon)
- Gestion des annulations et modifications de réservation
- Politique de retard (ex. : 15 minutes de retard = annulation automatique)
- Notifications (promotions, rappels de rendez-vous, etc.)
- Administration Django complète
---
 
## Technologies utilisées
 
- **Backend** : Django 5.x
- **Base de données** : PostgreSQL (recommandé) / SQLite (développement)
- **Frontend** : HTML5, CSS3, Bootstrap 5 / Tailwind CSS
- **Cartographie** : Leaflet ou Google Maps API
- **Paiement** : Stripe / Mobile Money (selon marché)
- **Autres** :
  - Django REST Framework (API)
  - Celery + Redis (tâches asynchrones : notifications, rappels)
  - Pillow (images)
  - django-allauth (authentification)
  - Channels (chat en temps réel – optionnel)
---
 
## Prérequis
 
- Python 3.11+
- pip + virtualenv
- PostgreSQL (recommandé)
- Redis (pour Celery)
- Git
---
 
## Installation
 
1. **Cloner le dépôt**
```bash
   git clone https://github.com/votre-utilisateur/bookmycoiff.git
   cd bookmycoiff
```
 
2. **Créer et activer l'environnement virtuel**
```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS / Linux
   source venv/bin/activate
```
 
3. **Installer les dépendances**
```bash
   pip install -r requirements.txt
```
 
4. **Configurer les variables d'environnement**
```bash
   cp .env.example .env
```
   Renseignez au minimum :
   - `SECRET_KEY`
   - `DEBUG`
   - `DATABASE_URL`
   - Clés API (Maps, Stripe, etc.)
5. **Appliquer les migrations**
```bash
   python manage.py migrate
```
 
6. **Créer un superutilisateur**
```bash
   python manage.py createsuperuser
```
 
7. **Lancer le serveur**
```bash
   python manage.py runserver
```
 
Accès :
- Site : http://127.0.0.1:8000
- Admin : http://127.0.0.1:8000/admin
---
 
## Structure du projet (proposée)
 
```text
bookmycoiff/
├── manage.py
├── requirements.txt
├── .env.example
├── README.md
├── config/                     # Settings, urls, wsgi/asgi
├── apps/
│   ├── accounts/               # Utilisateurs (clients, pros, admin)
│   ├── salons/                 # Salons, professionnels, équipements
│   ├── services/               # Catalogue de services + durées
│   ├── bookings/               # Réservations + créneaux
│   ├── reviews/                # Avis et notations
│   ├── loyalty/                # Points de fidélité + parrainage
│   ├── shop/                   # Boutique produits
│   ├── notifications/          # Notifications & promotions
│   └── core/                   # Pages statiques, utils
├── templates/
├── static/
└── media/
```
 
---
 
## Contribution
 
Les contributions sont les bienvenues !
 
### Comment contribuer
1. Forkez le projet
2. Créez une branche :
```bash
   git checkout -b feature/nom-de-la-fonctionnalite
```
3. Committez clairement :
```bash
   git commit -m "feat: ajout de la gestion des créneaux par professionnel"
```
4. Poussez et ouvrez une Pull Request
### Bonnes pratiques
- Respectez PEP 8
- Écrivez des messages de commit clairs (style Conventional Commits)
- Ajoutez des tests quand c'est pertinent
- Documentez les nouvelles fonctionnalités
- Une PR = une fonctionnalité ou un correctif
### Signalement de bugs / idées
Utilisez les Issues GitHub en précisant :
- Description claire
- Étapes de reproduction
- Comportement attendu vs observé
- Environnement (OS, version Python/Django)
---
 
## Roadmap (premières versions)
 
### Version 1 (MVP)
- Recherche de salons + géolocalisation
- Fiches salons
- Réservation de créneaux
- Gestion des horaires côté prestataire
- Système d'avis basique
### Versions suivantes
- Programme de fidélité & parrainage
- Boutique produits
- Chat interne
- Services à domicile
- Gestion des indépendants
- Paiements et commissions
---
 
## Licence
 
Ce projet est sous licence MIT. Voir le fichier `LICENSE`.
 
---
 
## Contact & équipe
 


Projet en phase de démarrage.
 
Équipe initiale prévue : 2 barbiers bêta-testeurs + développeur + commercial.
 
Pour toute question ou proposition de collaboration, ouvrez une issue ou contactez le mainteneur du dépôt.
Johniamzc8@gmail.com 
sekpona30@gmail.com
