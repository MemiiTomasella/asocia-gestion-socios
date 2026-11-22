"""Rutas principales del proyecto."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Login / logout (vistas incluidas en Django, plantilla en templates/registration/)
    path("accounts/", include("django.contrib.auth.urls")),
    # Aplicación principal
    path("", include("socios.urls")),
]
