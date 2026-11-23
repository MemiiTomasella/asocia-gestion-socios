"""Etiquetas de plantilla propias de Asocia."""
from urllib.parse import quote

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def whatsapp_recordatorio(context, socio):
    """Link de WhatsApp con un recordatorio de deuda ya redactado para el socio.

    Usa wa.me: abre WhatsApp (web o celular) con el mensaje escrito, y la persona
    de Secretaría decide si lo envía. No requiere ninguna API paga.
    Devuelve "" si el socio no tiene teléfono o no debe nada vencido.
    """
    cuenta = socio.estado_de_cuenta()
    if not socio.telefono_whatsapp or cuenta["cuotas_vencidas"] == 0:
        return ""
    n = cuenta["cuotas_vencidas"]
    institucion = context.get("institucion_nombre", "la institución")
    monto = f"{cuenta['deuda_vencida']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    mensaje = (
        f"Hola {socio.nombre}, te escribimos de {institucion}. "
        f"Te recordamos que tenés {n} cuota{'s' if n != 1 else ''} vencida{'s' if n != 1 else ''} "
        f"por un total de ${monto}. Podés acercarte a la sede para regularizar. ¡Gracias!"
    )
    return f"https://wa.me/{socio.telefono_whatsapp}?text={quote(mensaje)}"
