"""Vistas: dashboard, CRUD de socios, cuotas y pagos."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

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
@login_required
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
class SocioListView(LoginRequiredMixin, QuerystringMixin, ListView):
    template_name = "socios/socio_list.html"
    context_object_name = "socios"
    paginate_by = 10

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
        if estado in Socio.Estado.values:
            qs = qs.filter(estado=estado)
        if categoria.isdigit():
            qs = qs.filter(categoria_id=categoria)
        if params.get("moroso") == "1":
            qs = qs.filter(estado=Socio.Estado.ACTIVO, cuotas_vencidas__gt=0)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context.update(
            {
                "q": params.get("q", "").strip(),
                "estado": params.get("estado", ""),
                "categoria": params.get("categoria", ""),
                "moroso": params.get("moroso") == "1",
                "categorias": Categoria.objects.all(),
            }
        )
        return context


class SocioDetailView(LoginRequiredMixin, DetailView):
    model = Socio
    template_name = "socios/socio_detail.html"
    context_object_name = "socio"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cuotas"] = self.object.cuotas.prefetch_related("pagos")
        return context


class SocioCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Socio
    form_class = SocioForm
    template_name = "socios/socio_form.html"
    success_url = reverse_lazy("socios:socio_list")
    success_message = "El socio %(apellido)s, %(nombre)s se registró correctamente."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Nuevo socio"
        return context


class SocioUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Socio
    form_class = SocioForm
    template_name = "socios/socio_form.html"
    success_url = reverse_lazy("socios:socio_list")
    success_message = "Los datos de %(apellido)s, %(nombre)s se actualizaron correctamente."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Editar socio"
        return context


@login_required
@require_POST
def socio_baja(request, pk):
    """Baja lógica: el socio queda inactivo pero conserva su historial."""
    socio = get_object_or_404(Socio, pk=pk)
    socio.estado = Socio.Estado.INACTIVO
    socio.save(update_fields=["estado"])
    messages.warning(request, f"{socio.nombre_completo} fue dado de baja.")
    return redirect("socios:socio_list")


@login_required
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
class CuotaListView(LoginRequiredMixin, QuerystringMixin, ListView):
    template_name = "socios/cuota_list.html"
    context_object_name = "cuotas"
    paginate_by = 15

    def get_queryset(self):
        qs = Cuota.objects.select_related("socio")
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


class CuotaCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
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


@login_required
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
@login_required
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
            messages.success(
                request,
                f"Se registró el pago de ${pago.monto_pagado} de {cuota.socio.nombre_completo} "
                f"({cuota.periodo}).",
            )
            return redirect("socios:cuota_list")
    else:
        form = PagoForm(instance=pago, initial={"monto_pagado": cuota.saldo})

    return render(request, "socios/pago_form.html", {"form": form, "cuota": cuota})


class PagoListView(LoginRequiredMixin, QuerystringMixin, ListView):
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
