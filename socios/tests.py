"""Pruebas automáticas de los flujos principales. Ejecutar con: python manage.py test"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Categoria, Cuota, Pago, Socio


def crear_socio(dni="30111222", apellido="Rossi", nombre="Marco", categoria=None, **extra):
    categoria = categoria or Categoria.objects.get_or_create(
        nombre="Activo", defaults={"monto_cuota": Decimal("5000")}
    )[0]
    return Socio.objects.create(
        dni=dni, apellido=apellido, nombre=nombre,
        fecha_nacimiento="1985-05-10", categoria=categoria, **extra,
    )


class ModelosTests(TestCase):
    def setUp(self):
        self.socio = crear_socio()
        self.hoy = timezone.localdate()
        self.cuota = Cuota.objects.create(
            socio=self.socio, mes=self.hoy.month, anio=self.hoy.year,
            monto=Decimal("5000"), fecha_vencimiento=self.hoy + timedelta(days=5),
        )

    def test_pago_parcial_mantiene_pendiente_y_total_la_marca_pagada(self):
        Pago.objects.create(cuota=self.cuota, monto_pagado=Decimal("2000"))
        self.cuota.refresh_from_db()
        self.assertEqual(self.cuota.estado, Cuota.Estado.PENDIENTE)
        self.assertEqual(self.cuota.saldo, Decimal("3000"))

        Pago.objects.create(cuota=self.cuota, monto_pagado=Decimal("3000"))
        self.cuota.refresh_from_db()
        self.assertEqual(self.cuota.estado, Cuota.Estado.PAGADA)

    def test_eliminar_pago_vuelve_la_cuota_a_pendiente(self):
        pago = Pago.objects.create(cuota=self.cuota, monto_pagado=Decimal("5000"))
        self.cuota.refresh_from_db()
        self.assertEqual(self.cuota.estado, Cuota.Estado.PAGADA)
        pago.delete()
        self.cuota.refresh_from_db()
        self.assertEqual(self.cuota.estado, Cuota.Estado.PENDIENTE)

    def test_cuota_duplicada_para_el_mismo_periodo_no_es_valida(self):
        duplicada = Cuota(
            socio=self.socio, mes=self.cuota.mes, anio=self.cuota.anio,
            monto=Decimal("5000"), fecha_vencimiento=self.hoy,
        )
        with self.assertRaises(Exception):
            duplicada.full_clean()

    def test_cuota_vencida(self):
        self.cuota.fecha_vencimiento = self.hoy - timedelta(days=1)
        self.assertTrue(self.cuota.esta_vencida)


class VistasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("admin", password="clave-segura-123")
        cls.categoria = Categoria.objects.create(nombre="Activo", monto_cuota=Decimal("5000"))

    def setUp(self):
        self.client.login(username="admin", password="clave-segura-123")

    def test_vistas_requieren_login(self):
        self.client.logout()
        for nombre in ["dashboard", "socio_list", "cuota_list", "pago_list"]:
            resp = self.client.get(reverse(f"socios:{nombre}"))
            self.assertEqual(resp.status_code, 302, nombre)
            self.assertIn("/accounts/login/", resp["Location"])

    def test_paginas_principales_cargan(self):
        socio = crear_socio(categoria=self.categoria)
        urls = [
            reverse("socios:dashboard"), reverse("socios:socio_list"),
            reverse("socios:socio_create"), reverse("socios:socio_detail", args=[socio.pk]),
            reverse("socios:socio_update", args=[socio.pk]), reverse("socios:cuota_list"),
            reverse("socios:cuota_create"), reverse("socios:cuotas_generar"),
            reverse("socios:pago_list"),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_crear_socio(self):
        resp = self.client.post(reverse("socios:socio_create"), {
            "dni": "28999888", "nombre": "Giulia", "apellido": "Bianchi",
            "email": "giulia@example.com", "telefono": "3777123456", "direccion": "Colón 123",
            "fecha_nacimiento": "1990-03-15", "fecha_alta": "2026-01-10",
            "categoria": self.categoria.pk, "estado": "ACTIVO",
        })
        self.assertRedirects(resp, reverse("socios:socio_list"))
        self.assertTrue(Socio.objects.filter(dni="28999888").exists())

    def test_dni_invalido_y_duplicado(self):
        crear_socio(dni="30111222", categoria=self.categoria)
        datos = {
            "dni": "30111222", "nombre": "X", "apellido": "Y", "fecha_nacimiento": "1990-01-01",
            "fecha_alta": "2026-01-01", "categoria": self.categoria.pk, "estado": "ACTIVO",
        }
        resp = self.client.post(reverse("socios:socio_create"), datos)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Socio.objects.count(), 1)

        datos["dni"] = "12.345"
        resp = self.client.post(reverse("socios:socio_create"), datos)
        self.assertContains(resp, "El DNI debe tener 7 u 8 dígitos")

    def test_buscador_y_filtros(self):
        crear_socio(dni="30111222", apellido="Rossi", categoria=self.categoria)
        crear_socio(dni="25444555", apellido="Ferrari", nombre="Luca", categoria=self.categoria,
                    estado=Socio.Estado.INACTIVO)
        url = reverse("socios:socio_list")
        self.assertContains(self.client.get(url, {"q": "ferr"}), "Ferrari")
        self.assertNotContains(self.client.get(url, {"q": "ferr"}), "Rossi")
        self.assertContains(self.client.get(url, {"q": "30111"}), "Rossi")
        resp = self.client.get(url, {"estado": "INACTIVO"})
        self.assertContains(resp, "Ferrari")
        self.assertNotContains(resp, "Rossi")

    def test_baja_y_reactivacion_son_logicas_y_solo_post(self):
        socio = crear_socio(categoria=self.categoria)
        url_baja = reverse("socios:socio_baja", args=[socio.pk])
        self.assertEqual(self.client.get(url_baja).status_code, 405)
        self.client.post(url_baja)
        socio.refresh_from_db()
        self.assertEqual(socio.estado, Socio.Estado.INACTIVO)
        self.client.post(reverse("socios:socio_reactivar", args=[socio.pk]))
        socio.refresh_from_db()
        self.assertEqual(socio.estado, Socio.Estado.ACTIVO)

    def test_generar_cuotas_solo_para_activos_y_sin_duplicar(self):
        crear_socio(dni="30111222", categoria=self.categoria)
        crear_socio(dni="25444555", apellido="Ferrari", categoria=self.categoria,
                    estado=Socio.Estado.INACTIVO)
        datos = {"mes": 3, "anio": 2026, "fecha_vencimiento": "2026-03-10"}
        self.client.post(reverse("socios:cuotas_generar"), datos)
        self.assertEqual(Cuota.objects.count(), 1)
        self.assertEqual(Cuota.objects.first().monto, Decimal("5000"))
        self.client.post(reverse("socios:cuotas_generar"), datos)
        self.assertEqual(Cuota.objects.count(), 1)

    def test_cuota_sin_monto_usa_el_de_la_categoria(self):
        socio = crear_socio(categoria=self.categoria)
        resp = self.client.post(reverse("socios:cuota_create"), {
            "socio": socio.pk, "mes": 4, "anio": 2026, "monto": "", "fecha_vencimiento": "2026-04-10",
        })
        self.assertRedirects(resp, reverse("socios:cuota_list"))
        self.assertEqual(Cuota.objects.get().monto, Decimal("5000"))

    def test_cobro_de_cuota_y_validacion_de_monto(self):
        socio = crear_socio(categoria=self.categoria)
        cuota = Cuota.objects.create(
            socio=socio, mes=1, anio=2026, monto=Decimal("5000"), fecha_vencimiento="2026-01-10"
        )
        url = reverse("socios:pago_registrar", args=[cuota.pk])
        self.assertContains(self.client.get(url), "5000")

        # Monto mayor al saldo: se rechaza
        resp = self.client.post(url, {
            "fecha_pago": timezone.localdate().isoformat(),
            "monto_pagado": "9000", "metodo_pago": "EFECTIVO",
        })
        self.assertContains(resp, "supera el saldo")
        self.assertEqual(Pago.objects.count(), 0)

        # Pago correcto
        resp = self.client.post(url, {
            "fecha_pago": timezone.localdate().isoformat(),
            "monto_pagado": "5000", "metodo_pago": "TRANSFERENCIA",
        })
        self.assertRedirects(resp, reverse("socios:cuota_list"))
        cuota.refresh_from_db()
        self.assertEqual(cuota.estado, Cuota.Estado.PAGADA)

    def test_dashboard_cuenta_morosos_y_al_dia(self):
        moroso = crear_socio(dni="30111222", categoria=self.categoria)
        crear_socio(dni="25444555", apellido="Ferrari", categoria=self.categoria)
        Cuota.objects.create(
            socio=moroso, mes=1, anio=2026, monto=Decimal("5000"),
            fecha_vencimiento=timezone.localdate() - timedelta(days=30),
        )
        resp = self.client.get(reverse("socios:dashboard"))
        self.assertEqual(resp.context["total_socios"], 2)
        self.assertEqual(resp.context["morosos"], 1)
        self.assertEqual(resp.context["al_dia"], 1)
        listado = self.client.get(reverse("socios:socio_list"), {"moroso": "1"})
        self.assertContains(listado, "Rossi")
        self.assertNotContains(listado, "Ferrari")
