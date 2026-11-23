"""Registro de los modelos en el panel de administración de Django."""
from django.contrib import admin
from django.db.models import Count

from .models import AvisoPago, Categoria, Cuota, Pago, Socio

admin.site.site_header = "Asocia · Administración"
admin.site.site_title = "Gestión de socios"
admin.site.index_title = "Panel de administración"


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "monto_cuota", "cantidad_socios")
    search_fields = ("nombre",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_socios=Count("socios"))

    @admin.display(description="Socios", ordering="_socios")
    def cantidad_socios(self, obj):
        return obj._socios


@admin.action(description="Dar de baja los socios seleccionados")
def dar_de_baja(modeladmin, request, queryset):
    cantidad = queryset.update(estado=Socio.Estado.INACTIVO)
    modeladmin.message_user(request, f"{cantidad} socio(s) dado(s) de baja.")


@admin.action(description="Reactivar los socios seleccionados")
def reactivar(modeladmin, request, queryset):
    cantidad = queryset.update(estado=Socio.Estado.ACTIVO)
    modeladmin.message_user(request, f"{cantidad} socio(s) reactivado(s).")


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellido", "nombre", "categoria", "cargo", "email", "telefono", "estado", "fecha_alta")
    list_filter = ("estado", "categoria", "cargo")
    search_fields = ("dni", "apellido", "nombre", "email")
    list_select_related = ("categoria",)
    date_hierarchy = "fecha_alta"
    ordering = ("apellido", "nombre")
    actions = [dar_de_baja, reactivar]


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    fields = ("fecha_pago", "monto_pagado", "metodo_pago")


@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = ("socio", "periodo", "monto", "estado", "fecha_vencimiento", "vencida")
    list_filter = ("estado", "anio", "mes")
    search_fields = ("socio__dni", "socio__apellido", "socio__nombre")
    list_select_related = ("socio",)
    autocomplete_fields = ("socio",)
    date_hierarchy = "fecha_vencimiento"
    inlines = [PagoInline]

    @admin.display(description="Período", ordering="anio")
    def periodo(self, obj):
        return obj.periodo

    @admin.display(boolean=True, description="Vencida")
    def vencida(self, obj):
        return obj.esta_vencida


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("fecha_pago", "socio", "cuota", "monto_pagado", "metodo_pago")
    list_filter = ("metodo_pago", "fecha_pago")
    search_fields = ("cuota__socio__dni", "cuota__socio__apellido", "cuota__socio__nombre")
    list_select_related = ("cuota", "cuota__socio")
    autocomplete_fields = ("cuota",)
    date_hierarchy = "fecha_pago"

    @admin.display(description="Socio", ordering="cuota__socio__apellido")
    def socio(self, obj):
        return obj.cuota.socio



@admin.register(AvisoPago)
class AvisoPagoAdmin(admin.ModelAdmin):
    list_display = ("creado", "cuota", "monto", "fecha_transferencia", "numero_operacion", "estado", "revisado_por")
    list_filter = ("estado",)
