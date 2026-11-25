"""Formulaires des pages web (inscription d'un salon par son gérant)."""

from datetime import time

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.text import slugify

from .models import OpeningHours, Professional, Salon, Weekday

User = get_user_model()


class LoginForm(AuthenticationForm):
    """Connexion par e-mail : l'e-mail sert d'identifiant (username) à l'inscription."""

    username = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class OwnerSignupForm(forms.Form):
    """Compte du gérant, demandé seulement s'il n'est pas déjà connecté."""

    first_name = forms.CharField(label="Prénom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label="Nom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    email = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirmez le mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet e-mail. Connectez-vous pour ajouter votre salon.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
        elif p1:
            user = User(username=cleaned.get("email", ""), email=cleaned.get("email", ""),
                        first_name=cleaned.get("first_name", ""), last_name=cleaned.get("last_name", ""))
            try:
                password_validation.validate_password(p1, user)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self):
        data = self.cleaned_data
        return User.objects.create_user(
            username=data["email"], email=data["email"], password=data["password1"],
            first_name=data["first_name"], last_name=data["last_name"],
        )


# Horaires proposés par défaut : lundi → samedi, 8h-20h
DEFAULT_START, DEFAULT_END = time(8), time(20)


class SalonForm(forms.ModelForm):
    """Fiche du salon + horaires de la semaine (une plage par jour, modifiable ensuite)."""

    owner_is_pro = forms.BooleanField(
        label="Je coiffe aussi dans ce salon", required=False, initial=True,
        help_text="Crée votre profil de coiffeur pour que les clients puissent réserver avec vous.",
    )

    class Meta:
        model = Salon
        fields = [
            "name", "description", "cover_photo", "phone", "whatsapp", "email",
            "address", "city", "latitude", "longitude", "workstation_count", "offers_home_service",
        ]
        labels = {
            "name": "Nom du salon", "description": "Présentation", "phone": "Téléphone",
            "whatsapp": "WhatsApp", "email": "E-mail du salon", "address": "Adresse",
            "city": "Ville", "workstation_count": "Nombre de postes",
            "offers_home_service": "Je me déplace aussi à domicile",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "Spécialités, ambiance, ce qui vous distingue…"}),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "placeholder": "+228 90 00 00 00"}),
            "whatsapp": forms.TextInput(attrs={"type": "tel", "placeholder": "Si différent du téléphone"}),
            "address": forms.TextInput(attrs={"placeholder": "Rue, quartier, repère"}),
            "cover_photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "workstation_count": forms.NumberInput(attrs={"min": 1, "max": 50}),
        }
        error_messages = {
            "latitude": {"required": "Placez votre salon sur la carte."},
            "longitude": {"required": "Placez votre salon sur la carte."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].initial = "Lomé"
        self.fields["cover_photo"].label = "Photo de couverture"
        self.fields["cover_photo"].help_text = "La photo affichée sur votre carte dans les résultats."
        for day in Weekday:
            is_open = day != Weekday.SUNDAY
            self.fields[f"day{day.value}_open"] = forms.BooleanField(label=day.label, required=False, initial=is_open)
            self.fields[f"day{day.value}_start"] = forms.TimeField(
                required=False, initial=DEFAULT_START, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
            self.fields[f"day{day.value}_end"] = forms.TimeField(
                required=False, initial=DEFAULT_END, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    def hours_rows(self):
        """Lignes du tableau des horaires pour le template."""
        return [
            {"label": day.label, "open": self[f"day{day.value}_open"],
             "start": self[f"day{day.value}_start"], "end": self[f"day{day.value}_end"]}
            for day in Weekday
        ]

    def clean(self):
        cleaned = super().clean()
        self.opening_hours = []
        for day in Weekday:
            if not cleaned.get(f"day{day.value}_open"):
                continue
            start, end = cleaned.get(f"day{day.value}_start"), cleaned.get(f"day{day.value}_end")
            if not start or not end:
                self.add_error(f"day{day.value}_start", f"{day.label} : indiquez l'heure d'ouverture et de fermeture.")
            elif end <= start:
                self.add_error(f"day{day.value}_end", f"{day.label} : la fermeture doit être après l'ouverture.")
            else:
                self.opening_hours.append((day.value, start, end))
        if not self.opening_hours and not self.errors:
            raise forms.ValidationError("Indiquez au moins un jour d'ouverture.")
        return cleaned

    def save(self, owner):
        salon = super().save(commit=False)
        salon.owner = owner
        salon.slug = unique_salon_slug(salon.name)
        # Publié tout de suite (pas de validation manuelle pour l'instant)
        salon.is_published = True
        salon.save()
        OpeningHours.objects.bulk_create(
            OpeningHours(salon=salon, weekday=day, start_time=start, end_time=end)
            for day, start, end in self.opening_hours
        )
        if self.cleaned_data.get("owner_is_pro") and not hasattr(owner, "professional_profile"):
            Professional.objects.create(salon=salon, user=owner, display_name=owner.first_name or salon.name)
        return salon


def unique_salon_slug(name):
    base = slugify(name)[:40] or "salon"
    slug, n = base, 2
    while Salon.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


# ---------------------------------------------------------------------------
# Réservation par un client (sans compte)
# ---------------------------------------------------------------------------


def _clean_phone(value):
    import re

    if len(re.sub(r"\D", "", value)) < 8:
        raise forms.ValidationError("Numéro de téléphone incomplet.")
    return value.strip()


class BookingContactForm(forms.Form):
    client_name = forms.CharField(label="Votre nom", max_length=120,
                                  widget=forms.TextInput(attrs={"autocomplete": "name"}))
    client_phone = forms.CharField(
        label="Téléphone", max_length=30,
        help_text="Avec votre code, il permet de retrouver ou d'annuler la réservation.",
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "placeholder": "+228 90 00 00 00"}),
    )
    client_email = forms.EmailField(label="E-mail", required=False,
                                    widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    note = forms.CharField(label="Message pour le salon", max_length=300, required=False,
                           widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Ex. : coupe courte sur les côtés"}))

    def clean_client_phone(self):
        return _clean_phone(self.cleaned_data["client_phone"])


class BookingLookupForm(forms.Form):
    code = forms.CharField(label="Code de réservation", max_length=12,
                           widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off",
                                                         "placeholder": "Ex. : K7M2QX"}))
    phone = forms.CharField(label="Téléphone utilisé pour réserver", max_length=30,
                            widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}))

    def clean_phone(self):
        return _clean_phone(self.cleaned_data["phone"])
