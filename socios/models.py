"""Modelos de datos: Categoria, Socio, Cuota y Pago."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

MESES = [
    (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
    (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
    (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
]

MONTO_MINIMO = Decimal("0.01")

dni_validator = RegexValidator(
    r"^\d{7,8}$", "El DNI debe tener 7 u 8 dígitos, sin puntos ni espacios."
)


class Categoria(models.Model):
    """Categoría de socio (ej.: Activo, Adherente, Vitalicio, Cadete)."""

    nombre = models.CharField("Nombre", max_length=60, unique=True)
    monto_cuota = models.DecimalField(
        "Monto de la cuota",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(MONTO_MINIMO)],
    )
    descripcion = models.TextField("Descripción", blank=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} (${self.monto_cuota})"


class Socio(models.Model):
    """Persona asociada a la institución."""

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    dni = models.CharField("DNI", max_length=8, unique=True, validators=[dni_validator])
    nombre = models.CharField("Nombre", max_length=60)
    apellido = models.CharField("Apellido", max_length=60)
    email = models.EmailField("Email", blank=True)
    telefono = models.CharField("Teléfono", max_length=30, blank=True)
    direccion = models.CharField("Dirección", max_length=200, blank=True)
    fecha_nacimiento = models.DateField("Fecha de nacimiento")
    fecha_alta = models.DateField("Fecha de alta", default=timezone.localdate)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="socios",
        verbose_name="Categoría",
    )
    estado = models.CharField(
        "Estado", max_length=10, choices=Estado.choices, default=Estado.ACTIVO
    )

    class Meta:
        ordering = ["apellido", "nombre"]

    def __str__(self):
        return f"{self.apellido}, {self.nombre} ({self.dni})"

    @property
    def nombre_completo(self):
        return f"{self.apellido}, {self.nombre}"

    @property
    def esta_activo(self):
        return self.estado == self.Estado.ACTIVO

    @property
    def edad(self):
        hoy = timezone.localdate()
        nac = self.fecha_nacimiento
        return hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))

    def clean(self):
        if self.fecha_nacimiento and self.fecha_nacimiento > timezone.localdate():
            raise ValidationError(
                {"fecha_nacimiento": "La fecha de nacimiento no puede ser futura."}
            )


class Cuota(models.Model):
    """Cuota social mensual de un socio."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        PAGADA = "PAGADA", "Pagada"

    socio = models.ForeignKey(
        Socio, on_delete=models.PROTECT, related_name="cuotas", verbose_name="Socio"
    )
    mes = models.PositiveSmallIntegerField("Mes", choices=MESES)
    anio = models.PositiveSmallIntegerField(
        "Año", validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    monto = models.DecimalField(
        "Monto",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(MONTO_MINIMO)], 
        blank=True,
        null=True,
    )
    estado = models.CharField(
        "Estado", max_length=10, choices=Estado.choices, default=Estado.PENDIENTE
    )
    fecha_vencimiento = models.DateField("Fecha de vencimiento")

    class Meta:
        ordering = ["-anio", "-mes", "socio__apellido"]
        constraints = [
            models.UniqueConstraint(
                fields=["socio", "mes", "anio"],
                name="cuota_unica_por_socio_y_periodo",
                violation_error_message="Ese socio ya tiene una cuota para el mes y año indicados.",
            )
        ]

    def __str__(self):
        return f"{self.socio.nombre_completo} - {self.periodo}"

    @property
    def periodo(self):
        return f"{self.get_mes_display()} {self.anio}"

    @property
    def esta_vencida(self):
        return (
            self.estado == self.Estado.PENDIENTE
            and self.fecha_vencimiento < timezone.localdate()
        )

    @property
    def total_pagado(self):
        return sum((p.monto_pagado for p in self.pagos.all()), Decimal("0"))

    @property
    def saldo(self):
        return self.monto - self.total_pagado

    @property
    def es_parcial(self):
        """Pagada en partes: tiene pagos, pero todavía no cubren el monto total.

        No se guarda como estado en la base: se deduce de los pagos, así nunca
        puede quedar desactualizado (es un dato derivado).
        """
        return self.estado == self.Estado.PENDIENTE and self.total_pagado > 0

    def actualizar_estado(self):
        """Marca la cuota como pagada si los pagos cubren el monto; si no, pendiente."""
        total = self.pagos.aggregate(t=Sum("monto_pagado"))["t"] or Decimal("0")
        nuevo = self.Estado.PAGADA if total >= self.monto else self.Estado.PENDIENTE
        if nuevo != self.estado:
            self.estado = nuevo
            Cuota.objects.filter(pk=self.pk).update(estado=nuevo)

    def save(self, *args, **kwargs):
        # Si no se ingresó un monto, lo toma automáticamente de la categoría del socio
        if not self.monto and self.socio_id and self.socio.categoria:
            self.monto = self.socio.categoria.monto_cuota
            
        super().save(*args, **kwargs)
        # Si se edita el monto de una cuota con pagos, se recalcula el estado
        self.actualizar_estado()


class Pago(models.Model):
    """Pago (total o parcial) aplicado a una cuota."""

    class Metodo(models.TextChoices):
        EFECTIVO = "EFECTIVO", "Efectivo"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia bancaria"
        DEBITO = "DEBITO", "Tarjeta de débito"
        CREDITO = "CREDITO", "Tarjeta de crédito"
        MERCADOPAGO = "MERCADOPAGO", "Mercado Pago"

    cuota = models.ForeignKey(
        Cuota, on_delete=models.PROTECT, related_name="pagos", verbose_name="Cuota"
    )
    fecha_pago = models.DateField("Fecha de pago", default=timezone.localdate)
    monto_pagado = models.DecimalField(
        "Monto pagado",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(MONTO_MINIMO)],
    )
    metodo_pago = models.CharField(
        "Método de pago", max_length=15, choices=Metodo.choices, default=Metodo.EFECTIVO
    )

    class Meta:
        ordering = ["-fecha_pago", "-id"]

    def __str__(self):
        return f"Pago ${self.monto_pagado} - {self.cuota}"

    def clean(self):
        errores = {}
        if self.fecha_pago and self.fecha_pago > timezone.localdate():
            errores["fecha_pago"] = "La fecha de pago no puede ser futura."
        if self.cuota_id and self.monto_pagado is not None:
            ya_pagado = (
                self.cuota.pagos.exclude(pk=self.pk).aggregate(t=Sum("monto_pagado"))["t"]
                or Decimal("0")
            )
            saldo = self.cuota.monto - ya_pagado
            if self.monto_pagado > saldo:
                errores["monto_pagado"] = (
                    f"El monto supera el saldo pendiente de la cuota (${saldo})."
                )
        if errores:
            raise ValidationError(errores)


@receiver([post_save, post_delete], sender=Pago)
def sincronizar_estado_cuota(sender, instance, **kwargs):
    """Cada vez que se guarda o elimina un pago, se actualiza el estado de su cuota."""
    cuota = Cuota.objects.filter(pk=instance.cuota_id).first()
    if cuota:
        cuota.actualizar_estado()
        
@receiver(post_save, sender=Socio)
def crear_cuota_inicial_socio(sender, instance, created, **kwargs):
    """Crea automáticamente la cuota del mes actual cuando se da de alta un socio activo."""
    if created and instance.estado == Socio.Estado.ACTIVO:
        hoy = timezone.localdate()
        # Vence el día 10 del mes. Si el socio se asocia después del 10,
        # se le dan 10 días para pagar (si no, nacería ya moroso).
        if hoy.day <= 10:
            vencimiento = hoy.replace(day=10)
        else:
            vencimiento = hoy + timedelta(days=10)

        Cuota.objects.get_or_create(
            socio=instance,
            mes=hoy.month,
            anio=hoy.year,
            defaults={
                "monto": instance.categoria.monto_cuota,
                "estado": Cuota.Estado.PENDIENTE,
                "fecha_vencimiento": vencimiento,
            }
        )