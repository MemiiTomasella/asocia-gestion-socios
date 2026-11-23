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
        # Al dar de alta un socio activo, el sistema le crea sola la cuota del mes actual
        self.cuota = self.socio.cuotas.get(mes=self.hoy.month, anio=self.hoy.year)
        self.cuota.monto = Decimal("5000")
        self.cuota.fecha_vencimiento = self.hoy + timedelta(days=5)
        self.cuota.save()

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

    def test_cuota_pagada_en_partes_se_marca_como_parcial(self):
        self.assertFalse(self.cuota.es_parcial)  # sin pagos: pendiente, no parcial
        Pago.objects.create(cuota=self.cuota, monto_pagado=Decimal("2000"))
        self.cuota.refresh_from_db()
        self.assertTrue(self.cuota.es_parcial)  # pagó una parte
        Pago.objects.create(cuota=self.cuota, monto_pagado=Decimal("3000"))
        self.cuota.refresh_from_db()
        self.assertFalse(self.cuota.es_parcial)  # completó: ya es PAGADA
        self.assertEqual(self.cuota.estado, Cuota.Estado.PAGADA)

    def test_alta_de_socio_crea_la_cuota_del_mes_sin_nacer_moroso(self):
        socio = crear_socio(dni="27666777", apellido="Conti")
        cuota = socio.cuotas.get()
        self.assertEqual((cuota.mes, cuota.anio), (self.hoy.month, self.hoy.year))
        self.assertGreaterEqual(cuota.fecha_vencimiento, self.hoy)
        self.assertFalse(cuota.esta_vencida)

    def test_socio_dado_de_alta_inactivo_no_genera_cuota(self):
        socio = crear_socio(dni="27666888", estado=Socio.Estado.INACTIVO)
        self.assertFalse(socio.cuotas.exists())

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
        for nombre in ["dashboard", "socio_list", "cuota_list", "pago_list", "informes"]:
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
        marzo = Cuota.objects.filter(mes=3, anio=2026)
        self.client.post(reverse("socios:cuotas_generar"), datos)
        self.assertEqual(marzo.count(), 1)  # solo el socio activo
        self.assertEqual(marzo.first().monto, Decimal("5000"))
        self.client.post(reverse("socios:cuotas_generar"), datos)
        self.assertEqual(marzo.count(), 1)  # no se duplica

    def test_cuota_sin_monto_usa_el_de_la_categoria(self):
        socio = crear_socio(categoria=self.categoria)
        resp = self.client.post(reverse("socios:cuota_create"), {
            "socio": socio.pk, "mes": 4, "anio": 2026, "monto": "", "fecha_vencimiento": "2026-04-10",
        })
        self.assertRedirects(resp, reverse("socios:cuota_list"))
        self.assertEqual(Cuota.objects.get(mes=4, anio=2026).monto, Decimal("5000"))

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

    def test_cobro_parcial_y_filtro_de_parciales(self):
        socio = crear_socio(categoria=self.categoria)
        cuota = Cuota.objects.create(
            socio=socio, mes=1, anio=2026, monto=Decimal("5000"), fecha_vencimiento="2026-01-10"
        )
        url = reverse("socios:pago_registrar", args=[cuota.pk])
        resp = self.client.post(url, {
            "fecha_pago": timezone.localdate().isoformat(),
            "monto_pagado": "2000", "metodo_pago": "EFECTIVO",
        }, follow=True)
        self.assertContains(resp, "pago parcial")
        self.assertContains(resp, "Queda un saldo de $3000")

        listado = self.client.get(reverse("socios:cuota_list"), {"estado": "PARCIAL"})
        self.assertEqual([c.pk for c in listado.context["cuotas"]], [cuota.pk])
        self.assertContains(listado, "Cobrar saldo")

        # El formulario muestra el pago anterior y propone el saldo restante
        form = self.client.get(url)
        self.assertContains(form, "Pagos anteriores")
        self.assertEqual(form.context["form"].initial["monto_pagado"], Decimal("3000"))

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


class InformesTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user("admin", password="clave-segura-123")
        self.client.login(username="admin", password="clave-segura-123")
        self.url = reverse("socios:informes")

    def test_agrupa_altas_y_recaudacion_del_periodo_actual(self):
        socio = crear_socio()  # fecha de alta: hoy
        Pago.objects.create(cuota=socio.cuotas.get(), monto_pagado=Decimal("2000"))
        resp = self.client.get(self.url, {"agrupar": "mes"})
        actual = resp.context["filas"][-1]  # el último período es el mes en curso
        self.assertEqual(actual["altas"], 1)
        self.assertEqual(actual["recaudado"], Decimal("2000"))
        self.assertEqual(resp.context["total_recaudado"], Decimal("2000"))

    def test_cantidad_de_periodos_segun_agrupacion(self):
        for agrupar, cantidad in [("semana", 12), ("mes", 12), ("anio", 5), ("cualquiera", 12)]:
            resp = self.client.get(self.url, {"agrupar": agrupar})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(len(resp.context["filas"]), cantidad, agrupar)

    def test_pagos_fuera_del_rango_no_se_cuentan(self):
        socio = crear_socio()
        viejo = Cuota.objects.create(socio=socio, mes=1, anio=2020, monto=Decimal("5000"),
                                     fecha_vencimiento="2020-01-10")
        Pago.objects.create(cuota=viejo, monto_pagado=Decimal("5000"), fecha_pago="2020-01-05")
        resp = self.client.get(self.url, {"agrupar": "mes"})
        self.assertEqual(resp.context["total_recaudado"], Decimal("0"))

    def test_exportar_csv(self):
        resp = self.client.get(self.url, {"agrupar": "mes", "formato": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("Período;Altas de socios;Recaudado", resp.content.decode("utf-8-sig"))
