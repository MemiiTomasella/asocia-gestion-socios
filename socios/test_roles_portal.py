"""Pruebas de seguridad de roles y del portal del socio.

Verifican el principio de mínimo privilegio: cada rol solo accede a lo que le corresponde,
y un socio nunca puede ver ni tocar datos de otro socio.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import AvisoPago, Cuota, Pago
from .roles import DIRECTIVA, SECRETARIA, SOCIO, TESORERIA
from .tests import crear_socio, crear_usuario

CLAVE = "clave-segura-123"


class RolesTests(TestCase):
    def setUp(self):
        self.socio = crear_socio(dni="30111222")
        self.cuota = self.socio.cuotas.get()

    def entrar(self, rol):
        usuario = crear_usuario(username=f"u-{rol}", rol=rol)
        self.client.login(username=usuario.username, password=CLAVE)
        return usuario

    def test_comision_directiva_solo_consulta(self):
        self.entrar(DIRECTIVA)
        for nombre in ["dashboard", "socio_list", "cuota_list", "pago_list", "informes"]:
            self.assertEqual(self.client.get(reverse(f"socios:{nombre}")).status_code, 200, nombre)
        # No puede crear socios, cobrar ni generar cuotas
        self.assertEqual(self.client.get(reverse("socios:socio_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("socios:pago_registrar", args=[self.cuota.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("socios:cuotas_generar")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("socios:cuota_list")), "Cobrar")

    def test_tesoreria_cobra_pero_no_edita_socios(self):
        self.entrar(TESORERIA)
        self.assertEqual(self.client.get(reverse("socios:pago_registrar", args=[self.cuota.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("socios:socio_update", args=[self.socio.pk])).status_code, 403)
        resp = self.client.post(reverse("socios:socio_baja", args=[self.socio.pk]))
        self.assertEqual(resp.status_code, 403)
        self.socio.refresh_from_db()
        self.assertTrue(self.socio.esta_activo)  # la baja no se hizo

    def test_usuario_sin_rol_no_accede(self):
        self.entrar(None)
        self.assertEqual(self.client.get(reverse("socios:dashboard")).status_code, 403)

    def test_el_cargo_no_da_permisos(self):
        # Un socio que es presidente, si solo tiene rol Socio, no entra a la gestión
        self.socio.cargo = "PRESIDENTE"
        usuario = self.entrar(SOCIO)
        self.socio.usuario = usuario
        self.socio.save()
        self.assertRedirects(self.client.get(reverse("socios:dashboard")), reverse("socios:portal"))


class PortalSocioTests(TestCase):
    def setUp(self):
        # Secretaría crea el acceso al portal desde la ficha
        crear_usuario(username="secre", rol=SECRETARIA)
        self.client.login(username="secre", password=CLAVE)
        self.socio = crear_socio(dni="30111222", nombre="Marco")
        self.otro = crear_socio(dni="30999888", nombre="Giulia", apellido="Bianchi")
        resp = self.client.post(reverse("socios:socio_acceso_portal", args=[self.socio.pk]), follow=True)
        mensaje = str(list(resp.context["messages"])[0])
        self.clave = mensaje.split("Contraseña inicial: ")[1].split(" ")[0]
        self.socio.refresh_from_db()
        self.client.logout()

    def entrar_como_socio(self):
        self.assertTrue(self.client.login(username=self.socio.dni, password=self.clave))

    def test_crear_acceso_genera_usuario_con_rol_socio(self):
        self.assertEqual(self.socio.usuario.username, "30111222")
        self.assertTrue(self.socio.usuario.groups.filter(name=SOCIO).exists())
        self.assertFalse(self.socio.usuario.check_password("30111222"))  # la clave no es el DNI

    def test_socio_ve_su_cuenta_y_no_la_gestion(self):
        self.entrar_como_socio()
        resp = self.client.get(reverse("socios:portal"))
        self.assertContains(resp, "Hola, Marco")
        self.assertNotContains(resp, "Giulia")
        for nombre in ["dashboard", "socio_list", "cuota_list", "pago_list", "informes", "avisos_lista"]:
            self.assertRedirects(self.client.get(reverse(f"socios:{nombre}")), reverse("socios:portal"),
                                 msg_prefix=nombre)

    def test_socio_no_ve_comprobantes_de_otro(self):
        propio = Pago.objects.create(cuota=self.socio.cuotas.get(), monto_pagado=Decimal("1000"))
        ajeno = Pago.objects.create(cuota=self.otro.cuotas.get(), monto_pagado=Decimal("1000"))
        self.entrar_como_socio()
        self.assertEqual(self.client.get(reverse("socios:pago_comprobante", args=[propio.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("socios:pago_comprobante", args=[ajeno.pk])).status_code, 404)

    def test_socio_no_puede_avisar_pago_de_cuota_ajena(self):
        self.entrar_como_socio()
        cuota_ajena = self.otro.cuotas.get()
        resp = self.client.post(reverse("socios:portal_avisar_pago"), {
            "cuota": cuota_ajena.pk, "monto": "1000", "fecha_transferencia": "2026-01-05",
            "numero_operacion": "123",
        })
        self.assertEqual(resp.status_code, 200)  # vuelve el formulario con error
        self.assertFalse(AvisoPago.objects.exists())

    def test_flujo_completo_aviso_y_confirmacion(self):
        cuota = self.socio.cuotas.get()
        # 1) El socio avisa que transfirió una parte
        self.entrar_como_socio()
        self.client.post(reverse("socios:portal_avisar_pago"), {
            "cuota": cuota.pk, "monto": "2000", "fecha_transferencia": "2026-01-05",
            "numero_operacion": "OP-777",
        })
        aviso = AvisoPago.objects.get()
        self.assertEqual(aviso.estado, AvisoPago.Estado.PENDIENTE)
        self.assertFalse(Pago.objects.exists())  # todavía no es un pago
        # 2) Tesorería lo confirma: se crea el pago con su comprobante
        self.client.logout()
        crear_usuario(username="teso", rol=TESORERIA)
        self.client.login(username="teso", password=CLAVE)
        self.assertContains(self.client.get(reverse("socios:avisos_lista")), "OP-777")
        self.client.post(reverse("socios:aviso_confirmar", args=[aviso.pk]))
        aviso.refresh_from_db()
        self.assertEqual(aviso.estado, AvisoPago.Estado.CONFIRMADO)
        self.assertEqual(aviso.pago.monto_pagado, Decimal("2000"))
        self.assertEqual(aviso.pago.metodo_pago, Pago.Metodo.TRANSFERENCIA)
        cuota.refresh_from_db()
        self.assertTrue(cuota.es_parcial)
        # 3) No se puede confirmar dos veces
        self.assertEqual(self.client.post(reverse("socios:aviso_confirmar", args=[aviso.pk])).status_code, 404)

    def test_no_se_confirma_un_aviso_que_supera_el_saldo_actual(self):
        cuota = self.socio.cuotas.get()
        aviso = AvisoPago.objects.create(cuota=cuota, monto=cuota.monto, numero_operacion="X1")
        Pago.objects.create(cuota=cuota, monto_pagado=Decimal("1000"))  # mientras tanto pagó una parte en la sede
        crear_usuario(username="teso", rol=TESORERIA)
        self.client.login(username="teso", password=CLAVE)
        self.client.post(reverse("socios:aviso_confirmar", args=[aviso.pk]))
        aviso.refresh_from_db()
        self.assertEqual(aviso.estado, AvisoPago.Estado.PENDIENTE)
        self.assertEqual(Pago.objects.count(), 1)

    def test_socio_puede_cambiar_su_contrasena(self):
        self.entrar_como_socio()
        resp = self.client.post(reverse("password_change"), {
            "old_password": self.clave, "new_password1": "MiClaveNueva-2026", "new_password2": "MiClaveNueva-2026",
        })
        self.assertRedirects(resp, reverse("password_change_done"))
