"""Rutas de la aplicación 'socios'."""
from django.urls import path

from . import views, views_portal

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
    path("pagos/<int:pk>/comprobante/", views.pago_comprobante, name="pago_comprobante"),

    # Informes
    path("informes/", views.informes, name="informes"),

    # Portal del socio
    path("portal/", views_portal.portal, name="portal"),
    path("portal/avisar-pago/", views_portal.portal_avisar_pago, name="portal_avisar_pago"),
    path("socios/<int:pk>/acceso-portal/", views_portal.socio_acceso_portal, name="socio_acceso_portal"),

    # Avisos de pago (revisión por Secretaría / Tesorería)
    path("avisos/", views_portal.avisos_lista, name="avisos_lista"),
    path("avisos/<int:pk>/confirmar/", views_portal.aviso_confirmar, name="aviso_confirmar"),
    path("avisos/<int:pk>/rechazar/", views_portal.aviso_rechazar, name="aviso_rechazar"),
]
