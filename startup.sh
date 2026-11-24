#!/usr/bin/env bash
# Commande de démarrage Azure App Service (Paramètres → Configuration → Commande de démarrage : bash startup.sh).
# Azure a déjà activé l'environnement Python et installé requirements.txt à ce stade.
set -euo pipefail

# Applique les migrations à chaque démarrage (sans effet s'il n'y a rien de nouveau)
python manage.py migrate --noinput

# Premier administrateur : définir DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL et DJANGO_SUPERUSER_PASSWORD
# dans les paramètres de l'application, démarrer une fois, puis supprimer DJANGO_SUPERUSER_PASSWORD.
if [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py createsuperuser --noinput || echo "Administrateur déjà existant : rien à faire."
fi

# Les fichiers statiques sont déjà collectés par GitHub Actions (dossier staticfiles/ du paquet)
exec gunicorn barbershopProject.wsgi \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
