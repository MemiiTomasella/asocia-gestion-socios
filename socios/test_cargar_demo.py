"""Pruebas del comando 'python manage.py cargar_demo'."""
import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .models import Cuota, Pago, Socio
from .tests import crear_socio


class CargarDemoTests(TestCase):
    def test_carga_datos_variados_y_coherentes(self):
        call_command("cargar_demo", stdout=io.StringIO())
        hoy = timezone.localdate()
        self.assertEqual(Socio.objects.count(), 20)
        self.assertEqual(Socio.objects.filter(estado=Socio.Estado.INACTIVO).count(), 2)
        # Hay cuotas pagadas en partes y cuotas vencidas (morosos)
        self.assertTrue(any(c.es_parcial for c in Cuota.objects.filter(estado=Cuota.Estado.PENDIENTE)))
        self.assertTrue(Cuota.objects.filter(estado=Cuota.Estado.PENDIENTE, fecha_vencimiento__lt=hoy).exists())
        # Ningún pago a futuro ni pagos de más
        self.assertFalse(Pago.objects.filter(fecha_pago__gt=hoy).exists())
        for cuota in Cuota.objects.all():
            self.assertLessEqual(cuota.total_pagado, cuota.monto)

    def test_no_se_ejecuta_si_ya_hay_socios(self):
        crear_socio()
        with self.assertRaises(CommandError):
            call_command("cargar_demo", stdout=io.StringIO())
        self.assertEqual(Socio.objects.count(), 1)  # no agregó nada

    def test_reiniciar_borra_y_vuelve_a_cargar(self):
        crear_socio()
        call_command("cargar_demo", "--reiniciar", "--sin-confirmar", stdout=io.StringIO())
        self.assertEqual(Socio.objects.count(), 20)
        # La demo no incluye categorías que el sistema no maneja (por ej., grupo familiar)
        from .models import Categoria
        self.assertEqual(set(Categoria.objects.values_list("nombre", flat=True)), {"Activo", "Menor"})
        # Hay comisión directiva, y sus integrantes pagan la cuota de su categoría (el cargo no la cambia)
        self.assertEqual(Socio.objects.exclude(cargo="").count(), 4)
        self.assertFalse(Socio.objects.exclude(cargo="").exclude(categoria__nombre="Activo").exists())
