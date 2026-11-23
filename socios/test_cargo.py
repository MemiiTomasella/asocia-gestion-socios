"""Pruebas del cargo en la comisión directiva."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Socio
from .tests import crear_socio, crear_usuario


class CargoComisionDirectivaTests(TestCase):
    def setUp(self):
        crear_usuario()
        self.client.login(username="admin", password="clave-segura-123")
        self.presidente = crear_socio(dni="20111111", apellido="Rossi", cargo=Socio.Cargo.PRESIDENTE)
        self.comun = crear_socio(dni="20222222", apellido="Bianchi")

    def test_filtro_solo_comision_directiva(self):
        resp = self.client.get(reverse("socios:socio_list"), {"cargo": "DIRECTIVA"})
        self.assertEqual(list(resp.context["socios"]), [self.presidente])
        self.assertContains(resp, "Presidente/a")

    def test_el_cargo_no_cambia_la_cuota(self):
        # Ambos son de la misma categoría: pagan lo mismo aunque uno tenga cargo
        cuota_presidente = self.presidente.cuotas.get().monto
        cuota_comun = self.comun.cuotas.get().monto
        self.assertEqual(cuota_presidente, cuota_comun)

    def test_se_puede_asignar_el_cargo_desde_el_formulario(self):
        datos = {
            "dni": self.comun.dni, "nombre": self.comun.nombre, "apellido": self.comun.apellido,
            "fecha_nacimiento": "1985-05-10", "fecha_alta": "2026-01-01",
            "categoria": self.comun.categoria_id, "estado": "ACTIVO", "cargo": "TESORERO",
        }
        self.client.post(reverse("socios:socio_update", args=[self.comun.pk]), datos)
        self.comun.refresh_from_db()
        self.assertEqual(self.comun.get_cargo_display(), "Tesorero/a")


    def test_filtro_por_un_cargo_puntual(self):
        crear_socio(dni="20333333", apellido="Conti", cargo=Socio.Cargo.TESORERO)
        resp = self.client.get(reverse("socios:socio_list"), {"cargo": "TESORERO"})
        self.assertEqual([s.apellido for s in resp.context["socios"]], ["Conti"])

    def test_estado_al_dia_y_morosos_en_el_desplegable(self):
        from .models import Cuota
        Cuota.objects.create(socio=self.comun, mes=1, anio=2026, monto=5000, fecha_vencimiento="2026-01-10")
        morosos = self.client.get(reverse("socios:socio_list"), {"estado": "MOROSO"}).context["socios"]
        al_dia = self.client.get(reverse("socios:socio_list"), {"estado": "AL_DIA"}).context["socios"]
        self.assertEqual(list(morosos), [self.comun])
        self.assertEqual(list(al_dia), [self.presidente])
