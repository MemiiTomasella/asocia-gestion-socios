"""Pruebas de estado de cuenta, comprobante, recordatorio por WhatsApp y exportación del padrón."""
from decimal import Decimal
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Cuota, Pago, Socio
from .tests import crear_socio


class EstadoDeCuentaTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("admin", password="clave-segura-123")
        self.client.login(username="admin", password="clave-segura-123")
        self.categoria = Categoria.objects.create(nombre="Activo", monto_cuota=Decimal("5000"))
        self.socio = crear_socio(dni="27999888", categoria=self.categoria, telefono="3777-412345",
                                 estado=Socio.Estado.INACTIVO)  # inactivo: no genera la cuota del mes
        # Dos cuotas vencidas (una con pago parcial) y una a futuro
        self.ene = Cuota.objects.create(socio=self.socio, mes=1, anio=2026, monto=Decimal("5000"), fecha_vencimiento="2026-01-10")
        self.feb = Cuota.objects.create(socio=self.socio, mes=2, anio=2026, monto=Decimal("5000"), fecha_vencimiento="2026-02-10")
        Cuota.objects.create(socio=self.socio, mes=12, anio=2099, monto=Decimal("5000"), fecha_vencimiento="2099-12-10")
        self.pago = Pago.objects.create(cuota=self.feb, monto_pagado=Decimal("2000"), fecha_pago="2026-02-05")

    def test_estado_de_cuenta_suma_saldos(self):
        cuenta = self.socio.estado_de_cuenta()
        self.assertEqual(cuenta["deuda_total"], Decimal("13000"))   # 5000 + 3000 + 5000
        self.assertEqual(cuenta["deuda_vencida"], Decimal("8000"))  # 5000 + 3000
        self.assertEqual(cuenta["cuotas_impagas"], 3)
        self.assertEqual(cuenta["cuotas_vencidas"], 2)

    def test_ficha_muestra_deuda_y_recordatorio_de_whatsapp(self):
        resp = self.client.get(reverse("socios:socio_detail", args=[self.socio.pk]))
        self.assertContains(resp, "Total adeudado")
        self.assertContains(resp, "13.000,00")
        self.assertContains(resp, "https://wa.me/5493777412345?text=")
        link = [l for l in resp.content.decode().split('"') if l.startswith("https://wa.me/")][0]
        mensaje = unquote(link.split("text=")[1])
        self.assertIn("2 cuotas vencidas", mensaje)
        self.assertIn("$8.000,00", mensaje)

    def test_sin_telefono_no_hay_boton_de_whatsapp(self):
        self.socio.telefono = ""
        self.socio.save()
        resp = self.client.get(reverse("socios:socio_detail", args=[self.socio.pk]))
        self.assertNotContains(resp, "wa.me")
        self.assertContains(resp, "Cargá un teléfono")

    def test_telefono_en_formato_whatsapp(self):
        for cargado, esperado in [("3777-412345", "5493777412345"), ("03777 412345", "5493777412345"),
                                  ("+54 9 3777 412345", "5493777412345"), ("", "")]:
            self.socio.telefono = cargado
            self.assertEqual(self.socio.telefono_whatsapp, esperado, cargado)

    def test_comprobante_de_pago(self):
        resp = self.client.get(reverse("socios:pago_comprobante", args=[self.pago.pk]))
        self.assertContains(resp, f"{self.pago.pk:06d}")
        self.assertContains(resp, "Cuota social Febrero 2026")
        self.assertContains(resp, "pago parcial")
        self.assertContains(resp, "3.000,00")  # saldo pendiente de la cuota

    def test_exportar_padron_respeta_los_filtros(self):
        crear_socio(dni="30111222", apellido="Otro")  # activo y al día
        resp = self.client.get(reverse("socios:socio_list"), {"estado": "INACTIVO", "formato": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        contenido = resp.content.decode("utf-8-sig")
        self.assertIn("DNI;Apellido;Nombre", contenido)
        self.assertIn(self.socio.dni, contenido)
        self.assertNotIn("30111222", contenido)


class ComprobanteNoCambiaTests(TestCase):
    def test_comprobante_viejo_muestra_el_saldo_de_su_momento(self):
        get_user_model().objects.create_user("admin", password="clave-segura-123")
        self.client.login(username="admin", password="clave-segura-123")
        socio = crear_socio(dni="27999777", estado=Socio.Estado.INACTIVO)
        cuota = Cuota.objects.create(socio=socio, mes=3, anio=2026, monto=Decimal("5000"), fecha_vencimiento="2026-03-10")
        primero = Pago.objects.create(cuota=cuota, monto_pagado=Decimal("2000"), fecha_pago="2026-03-01")
        Pago.objects.create(cuota=cuota, monto_pagado=Decimal("3000"), fecha_pago="2026-03-08")  # completa la cuota
        resp = self.client.get(reverse("socios:pago_comprobante", args=[primero.pk]))
        self.assertEqual(resp.context["saldo_al_momento"], Decimal("3000"))  # no 0
        self.assertContains(resp, "pago parcial")
