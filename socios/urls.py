"""Rutas de la aplicación 'socios'."""
from django.urls import path

from . import views

app_name = "socios"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Socios
    path("socios/", views.SocioListView.as_view(), name="socio_list"),
    path("socios/nuevo/", views.SocioCreateView.as_view(), name="socio_create"),
    path("socios/<int:pk>/", views.SocioDetailView.as_view(), name="socio_detail"),
    path("socios/<int:pk>/editar/", views.SocioUpdateView.as_view(), name="socio_update"),
    path("socios/<int:pk>/baja/", views.socio_baja, name="socio_baja"),
    path("socios/<int:pk>/reactivar/", views.socio_reactivar, name="socio_reactivar"),

    # Cuotas
    path("cuotas/", views.CuotaListView.as_view(), name="cuota_list"),
    path("cuotas/nueva/", views.CuotaCreateView.as_view(), name="cuota_create"),
    path("cuotas/generar/", views.cuotas_generar, name="cuotas_generar"),

    # Pagos
    path("cuotas/<int:cuota_pk>/cobrar/", views.pago_registrar, name="pago_registrar"),
    path("pagos/", views.PagoListView.as_view(), name="pago_list"),
]
