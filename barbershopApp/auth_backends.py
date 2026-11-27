from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Connexion avec l'e-mail ou l'identifiant, sans tenir compte des majuscules.

    Les gérants inscrits sur le site ont leur e-mail comme identifiant ; les comptes créés
    autrement (admin, shell) ont un identifiant distinct mais peuvent aussi utiliser leur e-mail.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        User = get_user_model()
        candidates = list(User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)))
        # L'identifiant exact passe avant un e-mail partagé par plusieurs comptes
        candidates.sort(key=lambda u: u.username.lower() != username.lower())
        for user in candidates:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        if not candidates:
            User().set_password(password)  # même durée de réponse, que le compte existe ou non
        return None
