"""Vistas: dashboard, CRUD de socios, cuotas y pagos."""
import csv
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth, TruncWeek, TruncYear
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .roles import COBRAN, GESTIONAN_SOCIOS, PERSONAL, RolRequeridoMixin, rol_requerido, tiene_rol
from .forms import CuotaForm, GenerarCuotasForm, PagoForm, SocioForm
from .models import MESES, Categoria, Cuota, Pago, Socio


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def socios_con_mora(hoy=None):
    """Socios activos con al menos una cuota pendiente ya vencida."""
    hoy = hoy or timezone.localdate()
    return (
        Socio.objects.filter(estado=Socio.Estado.ACTIVO)
        .annotate(
            cuotas_vencidas=Count(
                "cuotas",
                filter=Q(
                    cuotas__estado=Cuota.Estado.PENDIENTE,
                    cuotas__fecha_vencimiento__lt=hoy,
                ),
            )
        )
        .filter(cuotas_vencidas__gt=0)
    )


class QuerystringMixin:
    """Agrega al contexto los filtros actuales (sin 'page') para la paginación."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        return context


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@rol_requerido(*PERSONAL)
def dashboard(request):
    hoy = timezone.localdate()

    total_socios = Socio.objects.count()
    socios_activos = Socio.objects.filter(estado=Socio.Estado.ACTIVO).count()
    morosos_qs = socios_con_mora(hoy)
    morosos = morosos_qs.count()
    al_dia = socios_activos - morosos

    cuotas_pendientes = Cuota.objects.filter(estado=Cuota.Estado.PENDIENTE).count()
    cuotas_vencidas = Cuota.objects.filter(
        estado=Cuota.Estado.PENDIENTE, fecha_vencimiento__lt=hoy
    ).count()
    recaudado_mes = (
        Pago.objects.filter(fecha_pago__year=hoy.year, fecha_pago__month=hoy.month)
        .aggregate(total=Sum("monto_pagado"))["total"]
        or 0
    )

    context = {
        "total_socios": total_socios,
        "socios_activos": socios_activos,
        "socios_inactivos": total_socios - socios_activos,
        "al_dia": al_dia,
        "morosos": morosos,
        "cuotas_pendientes": cuotas_pendientes,
        "cuotas_vencidas": cuotas_vencidas,
        "recaudado_mes": recaudado_mes,
        "mes_actual": dict(MESES)[hoy.month],
        "top_morosos": morosos_qs.select_related("categoria").order_by("-cuotas_vencidas", "apellido")[:5],
        "ultimos_pagos": Pago.objects.select_related("cuota__socio")[:5],
    }
    return render(request, "socios/dashboard.html", context)


# ---------------------------------------------------------------------------
# Socios (CRUD)
# ---------------------------------------------------------------------------
class SocioListView(RolRequeridoMixin, QuerystringMixin, ListView):
    roles = PERSONAL
    template_name = "socios/socio_list.html"
    context_object_name = "socios"
    paginate_by = 10

    def get(self, request, *args, **kwargs):
        # ?formato=csv descarga el padrón con los mismos filtros que se ven en pantalla
        if request.GET.get("formato") == "csv":
            return exportar_padron_csv(self.get_queryset())
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        hoy = timezone.localdate()
        qs = Socio.objects.select_related("categoria").annotate(
            cuotas_vencidas=Count(
                "cuotas",
                filter=Q(
                    cuotas__estado=Cuota.Estado.PENDIENTE,
                    cuotas__fecha_vencimiento__lt=hoy,
                ),
            )
        )
        params = self.request.GET
        q = params.get("q", "").strip()
        estado = params.get("estado", "")
        categoria = params.get("categoria", "")

        if q:
            qs = qs.filter(
                Q(dni__icontains=q)
                | Q(apellido__icontains=q)
                | Q(nombre__icontains=q)
                | Q(email__icontains=q)
            )
        # "Al día" y "Moroso" no son estados guardados: se deducen de las cuotas vencidas
        if estado == "MOROSO" or params.get("moroso") == "1":
            qs = qs.filter(estado=Socio.Estado.ACTIVO, cuotas_vencidas__gt=0)
        elif estado == "AL_DIA":
            qs = qs.filter(estado=Socio.Estado.ACTIVO, cuotas_vencidas=0)
        elif estado in Socio.Estado.values:
            qs = qs.filter(estado=estado)
        if categoria.isdigit():
            qs = qs.filter(categoria_id=categoria)
        cargo = params.get("cargo", "")
        if cargo == "DIRECTIVA" or params.get("directiva") == "1":
            qs = qs.exclude(cargo="")  # cualquier integrante de la comisión directiva
        elif cargo in Socio.Cargo.values:
            qs = qs.filter(cargo=cargo)
        # Con annotate(Count(...)) Django agrupa (GROUP BY) y deja de aplicar el
        # orden del Meta del modelo: lo indicamos explícito para que la paginación sea estable.
        return qs.order_by("apellido", "nombre")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context.update(
            {
                "q": params.get("q", "").strip(),
                "estado": params.get("estado", ""),
                "categoria": params.get("categoria", ""),
                "cargo": params.get("cargo", ""),
                "cargos": Socio.Cargo.choices,
                "categorias": Categoria.objects.all(),
            }
        )
        return context


class SocioDetailView(RolRequeridoMixin, DetailView):
    roles = PERSONAL
    model = Socio
    template_name = "socios/socio_detail.html"
    context_object_name = "socio"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cuotas"] = self.object.cuotas.prefetch_related("pagos")
        context["cuenta"] = self.object.estado_de_cuenta()
        return context


class SocioCreateView(RolRequeridoMixin, SuccessMessageMixin, CreateView):
    roles = GESTIONAN_SOCIOS
    model = Socio
    form_class = SocioForm
    template_name = "socios/socio_form.html"
    success_url = reverse_lazy("socios:socio_list")
    success_message = "El socio %(apellido)s, %(nombre)s se registró correctamente."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Nuevo socio"
        return context


class SocioUpdateView(RolRequeridoMixin, SuccessMessageMixin, UpdateView):
    roles = GESTIONAN_SOCIOS
    model = Socio
    form_class = SocioForm
    template_name = "socios/socio_form.html"
    success_url = reverse_lazy("socios:socio_list")
    success_message = "Los datos de %(apellido)s, %(nombre)s se actualizaron correctamente."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Editar socio"
        return context


@rol_requerido(*GESTIONAN_SOCIOS)
@require_POST
def socio_baja(request, pk):
    """Baja lógica: el socio queda inactivo pero conserva su historial."""
    socio = get_object_or_404(Socio, pk=pk)
    socio.estado = Socio.Estado.INACTIVO
    socio.save(update_fields=["estado"])
    messages.warning(request, f"{socio.nombre_completo} fue dado de baja.")
    return redirect("socios:socio_list")


@rol_requerido(*GESTIONAN_SOCIOS)
@require_POST
def socio_reactivar(request, pk):
    socio = get_object_or_404(Socio, pk=pk)
    socio.estado = Socio.Estado.ACTIVO
    socio.save(update_fields=["estado"])
    messages.success(request, f"{socio.nombre_completo} fue reactivado.")
    return redirect("socios:socio_list")


# ---------------------------------------------------------------------------
# Cuotas
# ---------------------------------------------------------------------------
class CuotaListView(RolRequeridoMixin, QuerystringMixin, ListView):
    roles = PERSONAL
    template_name = "socios/cuota_list.html"
    context_object_name = "cuotas"
    paginate_by = 15

    def get_queryset(self):
        # prefetch_related trae todos los pagos en una sola consulta extra,
        # en vez de una consulta por cada cuota al calcular lo pagado y el saldo.
        qs = Cuota.objects.select_related("socio").prefetch_related("pagos")
        params = self.request.GET
        q = params.get("q", "").strip()
        estado = params.get("estado", "")
        mes = params.get("mes", "")
        anio = params.get("anio", "")
        socio = params.get("socio", "")

        if q:
            qs = qs.filter(
                Q(socio__dni__icontains=q)
                | Q(socio__apellido__icontains=q)
                | Q(socio__nombre__icontains=q)
            )
        if estado == "PAGADA":
            qs = qs.filter(estado=Cuota.Estado.PAGADA)
        elif estado == "PENDIENTE":
            qs = qs.filter(estado=Cuota.Estado.PENDIENTE)
        elif estado == "PARCIAL":
            # Pendiente pero con al menos un pago: se pagó una parte
            qs = qs.filter(estado=Cuota.Estado.PENDIENTE, pagos__isnull=False).distinct()
        elif estado == "VENCIDA":
            qs = qs.filter(
                estado=Cuota.Estado.PENDIENTE, fecha_vencimiento__lt=timezone.localdate()
            )
        if mes.isdigit():
            qs = qs.filter(mes=mes)
        if anio.isdigit():
            qs = qs.filter(anio=anio)
        if socio.isdigit():
            qs = qs.filter(socio_id=socio)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context.update(
            {
                "q": params.get("q", "").strip(),
                "estado": params.get("estado", ""),
                "mes": params.get("mes", ""),
                "anio": params.get("anio", ""),
                "socio": params.get("socio", ""),
                "meses": MESES,
            }
        )
        return context


class CuotaCreateView(RolRequeridoMixin, SuccessMessageMixin, CreateView):
    roles = COBRAN
    model = Cuota
    form_class = CuotaForm
    template_name = "socios/cuota_form.html"
    success_url = reverse_lazy("socios:cuota_list")
    success_message = "La cuota se registró correctamente."

    def get_initial(self):
        hoy = timezone.localdate()
        initial = {
            "mes": hoy.month,
            "anio": hoy.year,
            "fecha_vencimiento": date(hoy.year, hoy.month, 10),
        }
        socio = self.request.GET.get("socio", "")
        if socio.isdigit():
            initial["socio"] = socio
        return initial


@rol_requerido(*COBRAN)
def cuotas_generar(request):
    """Genera la cuota del período elegido para todos los socios activos."""
    hoy = timezone.localdate()
    if request.method == "POST":
        form = GenerarCuotasForm(request.POST)
        if form.is_valid():
            mes = form.cleaned_data["mes"]
            anio = form.cleaned_data["anio"]
            vencimiento = form.cleaned_data["fecha_vencimiento"]

            existentes = set(
                Cuota.objects.filter(mes=mes, anio=anio).values_list("socio_id", flat=True)
            )
            nuevas = [
                Cuota(
                    socio=socio,
                    mes=mes,
                    anio=anio,
                    monto=socio.categoria.monto_cuota,
                    fecha_vencimiento=vencimiento,
                )
                for socio in Socio.objects.filter(estado=Socio.Estado.ACTIVO).select_related("categoria")
                if socio.pk not in existentes
            ]
            with transaction.atomic():
                Cuota.objects.bulk_create(nuevas)

            periodo = f"{dict(MESES)[mes]} {anio}"
            if nuevas:
                messages.success(
                    request,
                    f"Se generaron {len(nuevas)} cuota(s) de {periodo}. "
                    f"{len(existentes)} socio(s) ya tenían su cuota.",
                )
            else:
                messages.info(request, f"Todos los socios activos ya tienen la cuota de {periodo}.")
            return redirect("socios:cuota_list")
    else:
        form = GenerarCuotasForm(
            initial={
                "mes": hoy.month,
                "anio": hoy.year,
                "fecha_vencimiento": date(hoy.year, hoy.month, 10),
            }
        )
    return render(request, "socios/cuota_generar.html", {"form": form})


# ---------------------------------------------------------------------------
# Pagos
# ---------------------------------------------------------------------------
@rol_requerido(*COBRAN)
def pago_registrar(request, cuota_pk):
    """Cobro de una cuota: crea el pago y actualiza el estado de la cuota."""
    cuota = get_object_or_404(Cuota.objects.select_related("socio"), pk=cuota_pk)

    if cuota.estado == Cuota.Estado.PAGADA:
        messages.info(request, "Esa cuota ya está pagada.")
        return redirect("socios:cuota_list")

    pago = Pago(cuota=cuota)
    if request.method == "POST":
        form = PagoForm(request.POST, instance=pago)
        if form.is_valid():
            with transaction.atomic():
                pago = form.save()
            saldo = cuota.saldo
            if saldo > 0:
                messages.success(
                    request,
                    f"Se registró un pago parcial de ${pago.monto_pagado} de "
                    f"{cuota.socio.nombre_completo} ({cuota.periodo}). Queda un saldo de ${saldo}.",
                )
            else:
                messages.success(
                    request,
                    f"Se registró el pago de ${pago.monto_pagado} de {cuota.socio.nombre_completo} "
                    f"({cuota.periodo}). La cuota quedó saldada.",
                )
            # Después de cobrar se muestra el comprobante, listo para imprimir o guardar en PDF
            return redirect("socios:pago_comprobante", pk=pago.pk)
    else:
        form = PagoForm(instance=pago, initial={"monto_pagado": cuota.saldo})

    contexto = {"form": form, "cuota": cuota, "pagos_previos": cuota.pagos.all()}
    return render(request, "socios/pago_form.html", contexto)


class PagoListView(RolRequeridoMixin, QuerystringMixin, ListView):
    roles = PERSONAL
    template_name = "socios/pago_list.html"
    context_object_name = "pagos"
    paginate_by = 15

    def get_queryset(self):
        qs = Pago.objects.select_related("cuota__socio")
        params = self.request.GET
        q = params.get("q", "").strip()
        metodo = params.get("metodo", "")
        if q:
            qs = qs.filter(
                Q(cuota__socio__dni__icontains=q)
                | Q(cuota__socio__apellido__icontains=q)
                | Q(cuota__socio__nombre__icontains=q)
            )
        if metodo in Pago.Metodo.values:
            qs = qs.filter(metodo_pago=metodo)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context.update(
            {
                "q": params.get("q", "").strip(),
                "metodo": params.get("metodo", ""),
                "metodos": Pago.Metodo.choices,
                "total": self.object_list.aggregate(t=Sum("monto_pagado"))["t"] or 0,
            }
        )
        return context


# ---------------------------------------------------------------------------
# Informes: altas de socios y recaudación agrupadas por semana, mes o año
# ---------------------------------------------------------------------------
AGRUPACIONES = {
    # clave: (función SQL que "redondea" la fecha al inicio del período, cantidad de períodos, título)
    "semana": (TruncWeek, 12, "Últimas 12 semanas"),
    "mes": (TruncMonth, 12, "Últimos 12 meses"),
    "anio": (TruncYear, 5, "Últimos 5 años"),
}


def _inicios_de_periodo(agrupacion, cantidad, hoy):
    """Fecha de inicio de cada período a mostrar, de la más vieja a la más nueva."""
    if agrupacion == "semana":
        lunes = hoy - timedelta(days=hoy.weekday())
        return [lunes - timedelta(weeks=i) for i in range(cantidad - 1, -1, -1)]
    if agrupacion == "mes":
        inicios, anio, mes = [], hoy.year, hoy.month
        for _ in range(cantidad):
            inicios.append(date(anio, mes, 1))
            mes, anio = (12, anio - 1) if mes == 1 else (mes - 1, anio)
        return inicios[::-1]
    return [date(hoy.year - i, 1, 1) for i in range(cantidad - 1, -1, -1)]


def _etiqueta(agrupacion, inicio):
    if agrupacion == "semana":
        return f"Sem. {inicio:%d/%m}"
    if agrupacion == "mes":
        return f"{MESES[inicio.month - 1][1][:3]} {inicio.year}"
    return str(inicio.year)


def _como_fecha(valor):
    """Según el motor, Trunc devuelve date o datetime: lo normalizamos a date."""
    return valor.date() if hasattr(valor, "hour") else valor


@rol_requerido(*PERSONAL)
def informes(request):
    agrupacion = request.GET.get("agrupar", "mes")
    if agrupacion not in AGRUPACIONES:
        agrupacion = "mes"
    truncar, cantidad, titulo = AGRUPACIONES[agrupacion]
    hoy = timezone.localdate()
    inicios = _inicios_de_periodo(agrupacion, cantidad, hoy)
    desde = inicios[0]

    # SQL equivalente: SELECT DATE_TRUNC(...) AS periodo, COUNT(id) ... GROUP BY periodo
    altas = (
        Socio.objects.filter(fecha_alta__range=(desde, hoy))
        .annotate(periodo=truncar("fecha_alta"))
        .values("periodo")
        .annotate(total=Count("id"))
        .order_by("periodo")
    )
    recaudacion = (
        Pago.objects.filter(fecha_pago__range=(desde, hoy))
        .annotate(periodo=truncar("fecha_pago"))
        .values("periodo")
        .annotate(total=Sum("monto_pagado"))
        .order_by("periodo")
    )
    altas_por_periodo = {_como_fecha(f["periodo"]): f["total"] for f in altas}
    recaudado_por_periodo = {_como_fecha(f["periodo"]): f["total"] for f in recaudacion}

    # Completamos con 0 los períodos sin movimientos, para que el gráfico no tenga "huecos"
    filas = [
        {
            "etiqueta": _etiqueta(agrupacion, inicio),
            "altas": altas_por_periodo.get(inicio, 0),
            "recaudado": recaudado_por_periodo.get(inicio) or Decimal("0"),
        }
        for inicio in inicios
    ]

    if request.GET.get("formato") == "csv":
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = f'attachment; filename="informe_{agrupacion}_{hoy:%Y%m%d}.csv"'
        respuesta.write("\ufeff")  # BOM: para que Excel muestre bien los acentos
        escritor = csv.writer(respuesta, delimiter=";")  # ";" es el separador del Excel en español
        escritor.writerow(["Período", "Altas de socios", "Recaudado"])
        for fila in filas:
            escritor.writerow([fila["etiqueta"], fila["altas"], str(fila["recaudado"]).replace(".", ",")])
        return respuesta

    total_recaudado = sum((f["recaudado"] for f in filas), Decimal("0"))
    contexto = {
        "agrupacion": agrupacion,
        "titulo": titulo,
        "filas": filas,
        "total_altas": sum(f["altas"] for f in filas),
        "total_recaudado": total_recaudado,
        "promedio_recaudado": total_recaudado / len(filas),
        "socios_activos": Socio.objects.filter(estado=Socio.Estado.ACTIVO).count(),
        # Datos para Chart.js: se pasan con json_script (seguro ante inyección de código)
        "datos_grafico": {
            "etiquetas": [f["etiqueta"] for f in filas],
            "altas": [f["altas"] for f in filas],
            "recaudado": [float(f["recaudado"]) for f in filas],
        },
    }
    return render(request, "socios/informes.html", contexto)


# ---------------------------------------------------------------------------
# Comprobante de pago y exportación del padrón
# ---------------------------------------------------------------------------
@login_required
def pago_comprobante(request, pk):
    """Comprobante de un pago (RF-09). Se imprime o se guarda como PDF desde el navegador."""
    pago = get_object_or_404(Pago.objects.select_related("cuota__socio__categoria"), pk=pk)
    # Lo ve el personal de la institución, o el socio dueño del pago (desde su portal)
    es_el_duenio = pago.cuota.socio.usuario_id == request.user.pk
    if not (tiene_rol(request.user, *PERSONAL) or es_el_duenio):
        raise Http404("Comprobante inexistente")  # 404 y no 403: no revelamos que existe
    cuota = pago.cuota
    # Un comprobante no puede cambiar después de emitido: el saldo se calcula con los pagos
    # registrados HASTA este pago inclusive, no con los que se hayan hecho después.
    pagos_hasta_este = cuota.pagos.filter(
        Q(fecha_pago__lt=pago.fecha_pago) | Q(fecha_pago=pago.fecha_pago, pk__lte=pago.pk)
    )
    pagado_al_momento = pagos_hasta_este.aggregate(total=Sum("monto_pagado"))["total"]
    return render(request, "socios/pago_comprobante.html", {
        "pago": pago,
        "cuota": cuota,
        "socio": cuota.socio,
        "numero": f"{pago.pk:06d}",  # número de comprobante: 000123
        "pagado_al_momento": pagado_al_momento,
        "saldo_al_momento": cuota.monto - pagado_al_momento,
    })


def exportar_padron_csv(socios):
    hoy = timezone.localdate()
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="padron_socios_{hoy:%Y%m%d}.csv"'
    respuesta.write("\ufeff")  # BOM: para que Excel muestre bien los acentos
    escritor = csv.writer(respuesta, delimiter=";")
    escritor.writerow(["DNI", "Apellido", "Nombre", "Categoría", "Estado", "Fecha de alta",
                       "Teléfono", "Email", "Dirección", "Cuotas vencidas"])
    for socio in socios:
        escritor.writerow([
            socio.dni, socio.apellido, socio.nombre, socio.categoria.nombre,
            socio.get_estado_display(), f"{socio.fecha_alta:%d/%m/%Y}",
            socio.telefono, socio.email, socio.direccion, socio.cuotas_vencidas,
        ])
    return respuesta
