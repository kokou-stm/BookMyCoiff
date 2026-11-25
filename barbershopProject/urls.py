"""
URL configuration for barbershopProject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from barbershopApp.forms import LoginForm
from barbershopApp.views import (
    booking_cancel,
    booking_detail,
    booking_lookup,
    booking_page,
    home,
    my_salons,
    salon_register,
)

urlpatterns = [
    path('', home, name='home'),
    path('inscrire-mon-salon/', salon_register, name='salon_register'),
    path('mes-salons/', my_salons, name='my_salons'),
    # Réservation client (sans compte)
    path('salons/<slug:slug>/reserver/', booking_page, name='booking'),
    path('reservation/', booking_lookup, name='booking_lookup'),
    path('reservation/<str:code>/', booking_detail, name='booking_detail'),
    path('reservation/<str:code>/annuler/', booking_cancel, name='booking_cancel'),
    path('connexion/', auth_views.LoginView.as_view(
        template_name='barbershopApp/login.html', authentication_form=LoginForm, redirect_authenticated_user=True,
    ), name='login'),
    path('deconnexion/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('barbershopApp.urls')),
    path('api-auth/', include('rest_framework.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
