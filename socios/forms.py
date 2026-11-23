"""Formularios de la aplicación (con estilos de Bootstrap 5)."""
from django import forms
from django.utils import timezone

from .models import MESES, Cuota, Pago, Socio


def fecha_widget():
    """Selector de fecha nativo del navegador (<input type="date">)."""
    return forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class BootstrapFormMixin:
    """Agrega las clases de Bootstrap a todos los campos y marca los inválidos."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            clase = "form-select" if isinstance(widget, forms.Select) else "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {clase}".strip()

    def full_clean(self):
        super().full_clean()
        for nombre in self.errors:
            if nombre in self.fields:
                widget = self.fields[nombre].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()


class SocioForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Socio
        fields = [
            "dni", "nombre", "apellido", "email", "telefono", "direccion",
            "fecha_nacimiento", "fecha_alta", "categoria", "estado", "cargo",
        ]
        widgets = {
            "dni": forms.TextInput(
                attrs={"inputmode": "numeric", "maxlength": "8", "placeholder": "Sin puntos"}
            ),
            "fecha_nacimiento": fecha_widget(),
            "fecha_alta": fecha_widget(),
        }
        help_texts = {"dni": "7 u 8 dígitos, sin puntos."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].empty_label = "Seleccionar categoría..."
        self.fields["cargo"].choices = [("", "Sin cargo")] + list(Socio.Cargo.choices)


class CuotaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Cuota
        fields = ["socio", "mes", "anio", "monto", "fecha_vencimiento"]
        widgets = {"fecha_vencimiento": fecha_widget()}
        help_texts = {"monto": "Dejalo vacío para usar el monto de la categoría del socio."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["socio"].queryset = Socio.objects.filter(
            estado=Socio.Estado.ACTIVO
        ).select_related("categoria")
        self.fields["socio"].empty_label = "Seleccionar socio..."
        self.fields["monto"].required = False

    def clean(self):
        cleaned = super().clean()
        socio = cleaned.get("socio")
        if socio and not cleaned.get("monto"):
            cleaned["monto"] = socio.categoria.monto_cuota
        return cleaned


class GenerarCuotasForm(BootstrapFormMixin, forms.Form):
    """Genera la cuota de un período para todos los socios activos."""

    mes = forms.TypedChoiceField(choices=MESES, coerce=int, label="Mes")
    anio = forms.IntegerField(label="Año", min_value=2000, max_value=2100)
    fecha_vencimiento = forms.DateField(label="Fecha de vencimiento", widget=fecha_widget())


class PagoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Pago
        fields = ["fecha_pago", "monto_pagado", "metodo_pago"]
        widgets = {"fecha_pago": fecha_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_pago"].initial = timezone.localdate()
