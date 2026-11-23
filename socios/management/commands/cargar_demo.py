"""Carga datos de demostración (ficticios) en una base vacía.

Uso:  python manage.py cargar_demo              (solo si la base no tiene socios)
      python manage.py cargar_demo --reiniciar  (borra los datos y vuelve a cargar; pide confirmación)

Crea categorías, ~20 socios con nombres inventados, sus cuotas mensuales desde
la fecha de alta y pagos con distintos comportamientos: socios al día, socios
que pagan en partes y socios morosos. Así el panel, el semáforo de cuotas y los
informes muestran situaciones reales para la presentación.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from socios.models import Categoria, Cuota, Pago, Socio

CATEGORIAS = [
    ("Activo", Decimal("6000"), "Socio adulto con todos los derechos."),
    ("Menor", Decimal("3000"), "Socios menores de 18 años."),
]

# Nombres inventados: no corresponden a personas reales
SOCIOS = [
    ("Rossi", "Marco"), ("Bianchi", "Giulia"), ("Ferrari", "Luca"), ("Conti", "Sofía"),
    ("Romano", "Andrés"), ("Gallo", "Lucía"), ("Costa", "Matías"), ("Ricci", "Valentina"),
    ("Greco", "Tomás"), ("Bruno", "Camila"), ("Moretti", "Joaquín"), ("Mancini", "Martina"),
    ("Lombardi", "Franco"), ("Barbieri", "Paula"), ("Fontana", "Nicolás"), ("Santoro", "Abril"),
    ("Marino", "Ignacio"), ("Caruso", "Florencia"), ("Rinaldi", "Bruno"), ("Esposito", "Delfina"),
]

# Hace cuántos días se asoció cada uno (más altas en los últimos meses)
DIAS_DESDE_EL_ALTA = [362, 352, 330, 301, 296, 262, 236, 229, 199, 171,
                      166, 128, 99, 93, 62, 58, 41, 25, 12, 4]

METODOS = [Pago.Metodo.EFECTIVO] * 4 + [Pago.Metodo.TRANSFERENCIA] * 3 + [
    Pago.Metodo.MERCADOPAGO, Pago.Metodo.DEBITO]


def meses_entre(desde, hasta):
    """Lista de (año, mes) desde el mes de 'desde' hasta el mes de 'hasta', inclusive."""
    anio, mes, resultado = desde.year, desde.month, []
    while (anio, mes) <= (hasta.year, hasta.month):
        resultado.append((anio, mes))
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return resultado


class Command(BaseCommand):
    help = "Carga socios, cuotas y pagos ficticios para la demostración (solo en una base sin socios)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reiniciar", action="store_true",
            help="Borra TODOS los socios, cuotas, pagos y categorías antes de cargar la demo.",
        )
        parser.add_argument("--sin-confirmar", action="store_true", help="No pide confirmación (para tests).")

    def handle(self, *args, **options):
        if options["reiniciar"]:
            if not options["sin_confirmar"]:
                respuesta = input("Esto BORRA todos los socios, cuotas, pagos y categorías. Escribí BORRAR para seguir: ")
                if respuesta.strip() != "BORRAR":
                    raise CommandError("Cancelado: no se borró nada.")
            with transaction.atomic():
                # Se borra de "abajo hacia arriba" porque las claves foráneas usan PROTECT
                Pago.objects.all().delete()
                Cuota.objects.all().delete()
                Socio.objects.all().delete()
                Categoria.objects.all().delete()
            self.stdout.write("Datos anteriores borrados.")
        if Socio.objects.exists():
            raise CommandError(
                "La base ya tiene socios. Este comando es solo para una base vacía, "
                "así nunca se mezclan datos de prueba con datos reales."
            )
        azar = random.Random(2026)  # semilla fija: siempre genera los mismos datos
        hoy = timezone.localdate()

        with transaction.atomic():  # o se carga todo, o no se carga nada
            categorias = [
                Categoria.objects.get_or_create(
                    nombre=nombre, defaults={"monto_cuota": monto, "descripcion": desc}
                )[0]
                for nombre, monto, desc in CATEGORIAS
            ]

            # Comportamiento de pago de cada socio. Los dos más antiguos se dieron de baja;
            # el resto se reparte al azar entre al día, pagos en partes y morosos.
            resto = (["al_dia"] * 11) + (["parcial"] * 3) + (["moroso"] * 4)
            azar.shuffle(resto)
            perfiles = ["inactivo", "inactivo"] + resto

            totales = {"socios": 0, "cuotas": 0, "pagos": 0}
            cargos_pendientes = [Socio.Cargo.PRESIDENTE, Socio.Cargo.SECRETARIO,
                                 Socio.Cargo.TESORERO, Socio.Cargo.VOCAL]
            for i, ((apellido, nombre), dias, perfil) in enumerate(zip(SOCIOS, DIAS_DESDE_EL_ALTA, perfiles)):
                alta = hoy - timedelta(days=dias)
                # Casi todos son "Activo"; algunos "Menor" (cuota reducida)
                categoria = categorias[1] if i in (5, 11, 17) else categorias[0]
                socio = Socio.objects.create(
                    # Los menores (nacidos 2009-2012) tienen DNI de numeración más alta
                    dni=str(azar.randint(49_000_000, 53_999_999) if categoria == categorias[1]
                            else azar.randint(20_000_000, 45_999_999)),
                    nombre=nombre, apellido=apellido,
                    email=f"{nombre.lower()}.{apellido.lower()}@ejemplo.com".replace("í", "i").replace("á", "a").replace("ó", "o"),
                    telefono=f"3777-{azar.randint(400000, 699999)}",
                    direccion=f"Calle {azar.randint(1, 40)} N° {azar.randint(100, 2500)}",
                    fecha_nacimiento=date(
                        azar.randint(2009, 2012) if categoria.nombre == "Menor" else azar.randint(1955, 2005),
                        azar.randint(1, 12), azar.randint(1, 28)),
                    fecha_alta=alta,
                    categoria=categoria,
                    estado=Socio.Estado.INACTIVO if perfil == "inactivo" else Socio.Estado.ACTIVO,
                )
                if perfil == "al_dia" and categoria == categorias[0] and cargos_pendientes:
                    # La comisión directiva: algunos socios al día ocupan un cargo (no cambia su cuota)
                    socio.cargo = cargos_pendientes.pop(0)
                    socio.save(update_fields=["cargo"])
                totales["socios"] += 1

                # Los inactivos pagaron hasta que se dieron de baja (3 meses antes de hoy)
                hasta = hoy - timedelta(days=95) if perfil == "inactivo" else hoy
                periodos = meses_entre(alta, hasta)
                for n, (anio, mes) in enumerate(periodos):
                    ultimo = n == len(periodos) - 1
                    vence = date(anio, mes, 10)
                    if ultimo and perfil != "inactivo" and alta.year == anio and alta.month == mes:
                        vence = max(vence, alta + timedelta(days=10))  # recién asociado: 10 días de gracia
                    cuota, _ = Cuota.objects.update_or_create(  # la del mes actual ya la creó la señal
                        socio=socio, mes=mes, anio=anio,
                        defaults={"monto": categoria.monto_cuota, "fecha_vencimiento": vence},
                    )
                    totales["cuotas"] += 1

                    # ¿Cuánto paga de esta cuota?
                    meses_que_debe = 1 + (i % 3)  # los morosos dejaron de pagar 1 a 3 meses
                    if perfil == "moroso" and n >= len(periodos) - meses_que_debe:
                        continue
                    monto = cuota.monto
                    if perfil == "parcial" and ultimo:
                        monto = (cuota.monto * Decimal(azar.choice(["0.4", "0.5", "0.6"]))).quantize(Decimal("1"))
                    fecha_pago = min(vence - timedelta(days=azar.randint(0, 8)), hoy)
                    if fecha_pago < alta:
                        fecha_pago = alta
                    if ultimo and perfil == "al_dia" and fecha_pago > hoy:
                        continue
                    if perfil == "parcial" and ultimo and monto < cuota.monto:
                        # Pagó una parte en dos veces (pago en partes)
                        mitad = (monto / 2).quantize(Decimal("1"))
                        Pago.objects.create(cuota=cuota, monto_pagado=mitad, fecha_pago=fecha_pago,
                                            metodo_pago=azar.choice(METODOS))
                        Pago.objects.create(cuota=cuota, monto_pagado=monto - mitad, fecha_pago=hoy,
                                            metodo_pago=azar.choice(METODOS))
                        totales["pagos"] += 2
                    else:
                        Pago.objects.create(cuota=cuota, monto_pagado=monto, fecha_pago=fecha_pago,
                                            metodo_pago=azar.choice(METODOS))
                        totales["pagos"] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Datos de demo cargados: {totales['socios']} socios, "
            f"{totales['cuotas']} cuotas y {totales['pagos']} pagos."
        ))
