"""Portal del socio, avisos de pago por transferencia y accesos al portal."""
import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AvisoPagoForm
from .models import AvisoPago, Pago, Socio
from .roles import COBRAN, GESTIONAN_SOCIOS, SOCIO, es_socio, rol_requerido, tiene_rol


# ---------------------------------------------------------------------------
# Portal del socio (rol Socio)
# ---------------------------------------------------------------------------
def _socio_del_usuario(request):
    """El socio vinculado al usuario que inició sesión (o None)."""
    return Socio.objects.filter(usuario=request.user).select_related("categoria").first()


@rol_requerido(SOCIO)
def portal(request):
    socio = _socio_del_usuario(request)
    if socio is None:
        return render(request, "socios/portal_sin_socio.html")
    cuotas = socio.cuotas.prefetch_related("pagos")
    return render(request, "socios/portal.html", {
        "socio": socio,
        "cuenta": socio.estado_de_cuenta(),  # el mismo cálculo que ve Secretaría en la ficha
        "cuotas": cuotas,
        "avisos": AvisoPago.objects.filter(cuota__socio=socio).select_related("cuota")[:10],
    })


@rol_requerido(SOCIO)
def portal_avisar_pago(request):
    socio = _socio_del_usuario(request)
    if socio is None:
        return redirect("socios:portal")
    inicial = {}
    if request.GET.get("cuota", "").isdigit():
        cuota = socio.cuotas.filter(pk=request.GET["cuota"]).first()  # solo cuotas propias
        if cuota:
            inicial = {"cuota": cuota, "monto": cuota.saldo}
    form = AvisoPagoForm(request.POST or None, socio=socio, initial=inicial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "¡Gracias! Recibimos tu aviso. Cuando la institución lo confirme, "
                                  "vas a ver el pago y su comprobante en tu cuenta.")
        return redirect("socios:portal")
    return render(request, "socios/portal_aviso_form.html", {"form": form, "socio": socio})


# ---------------------------------------------------------------------------
# Revisión de avisos (Secretaría y Tesorería)
# ---------------------------------------------------------------------------
@rol_requerido(*COBRAN)
def avisos_lista(request):
    pendientes = AvisoPago.objects.filter(estado=AvisoPago.Estado.PENDIENTE).select_related("cuota__socio")
    revisados = AvisoPago.objects.exclude(estado=AvisoPago.Estado.PENDIENTE).select_related(
        "cuota__socio", "revisado_por", "pago")[:15]
    return render(request, "socios/avisos_lista.html", {"pendientes": pendientes, "revisados": revisados})


@require_POST
@rol_requerido(*COBRAN)
def aviso_confirmar(request, pk):
    aviso = get_object_or_404(AvisoPago, pk=pk, estado=AvisoPago.Estado.PENDIENTE)
    cuota = aviso.cuota
    # Se vuelve a validar: entre el aviso y la confirmación pudo haberse cobrado otra parte
    if aviso.monto > cuota.saldo:
        messages.error(request, f"No se puede confirmar: el aviso (${aviso.monto}) supera el saldo "
                                f"actual de la cuota (${cuota.saldo}). Revisalo o rechazalo.")
        return redirect("socios:avisos_lista")
    with transaction.atomic():  # o se crea el pago y se marca el aviso, o no pasa nada
        pago = Pago.objects.create(
            cuota=cuota, monto_pagado=aviso.monto, fecha_pago=aviso.fecha_transferencia,
            metodo_pago=Pago.Metodo.TRANSFERENCIA,
        )
        aviso.estado, aviso.pago, aviso.revisado_por = AvisoPago.Estado.CONFIRMADO, pago, request.user
        aviso.save()
    messages.success(request, f"Aviso confirmado: se registró el pago de ${aviso.monto} de "
                              f"{cuota.socio.nombre_completo} ({cuota.periodo}).")
    return redirect("socios:avisos_lista")


@require_POST
@rol_requerido(*COBRAN)
def aviso_rechazar(request, pk):
    aviso = get_object_or_404(AvisoPago, pk=pk, estado=AvisoPago.Estado.PENDIENTE)
    aviso.estado, aviso.revisado_por = AvisoPago.Estado.RECHAZADO, request.user
    aviso.save()
    messages.info(request, f"Aviso de {aviso.cuota.socio.nombre_completo} rechazado.")
    return redirect("socios:avisos_lista")


# ---------------------------------------------------------------------------
# Acceso al portal (Secretaría): crea o restablece el usuario del socio
# ---------------------------------------------------------------------------
@require_POST
@rol_requerido(*GESTIONAN_SOCIOS)
def socio_acceso_portal(request, pk):
    socio = get_object_or_404(Socio, pk=pk)
    clave = secrets.token_urlsafe(6)  # contraseña inicial aleatoria (no se guarda en texto plano)
    Usuario = get_user_model()
    with transaction.atomic():
        usuario = socio.usuario
        if usuario is None:
            usuario = Usuario.objects.filter(username=socio.dni).first() or Usuario(username=socio.dni)
            usuario.first_name, usuario.last_name, usuario.email = socio.nombre, socio.apellido, socio.email
        usuario.set_password(clave)  # Django guarda solo el hash de la contraseña
        usuario.save()
        usuario.groups.add(Group.objects.get(name=SOCIO))
        socio.usuario = usuario
        socio.save(update_fields=["usuario"])
    messages.success(
        request,
        f"Acceso al portal listo para {socio.nombre_completo}. Usuario: {usuario.username} · "
        f"Contraseña inicial: {clave} — entregásela al socio; podrá cambiarla al ingresar.",
    )
    return redirect("socios:socio_detail", pk=socio.pk)
