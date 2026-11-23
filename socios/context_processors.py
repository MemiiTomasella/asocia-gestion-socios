"""Variables disponibles en todas las plantillas."""
from django.conf import settings


def institucion(request):
    """Nombre de la institución que usa Asocia (se configura con la variable INSTITUCION_NOMBRE)."""
    return {"institucion_nombre": settings.INSTITUCION_NOMBRE}


def permisos(request):
    """Qué puede hacer el usuario: las plantillas muestran u ocultan menús y botones según esto.

    Ocultar un botón es solo comodidad: la seguridad real está en las vistas (socios/roles.py),
    que rechazan el acceso aunque alguien escriba la dirección a mano.
    """
    from .models import AvisoPago
    from .roles import COBRAN, GESTIONAN_SOCIOS, PERSONAL, es_socio, roles_de, tiene_rol

    usuario = request.user
    if not usuario.is_authenticated:
        return {}
    puede_cobrar = tiene_rol(usuario, *COBRAN)
    return {
        "es_personal": tiene_rol(usuario, *PERSONAL),
        "puede_gestionar_socios": tiene_rol(usuario, *GESTIONAN_SOCIOS),
        "puede_cobrar": puede_cobrar,
        "es_socio_portal": es_socio(usuario),
        "rol_actual": "Administrador" if usuario.is_superuser else ", ".join(sorted(roles_de(usuario))) or "Sin rol",
        "avisos_pendientes": AvisoPago.objects.filter(estado=AvisoPago.Estado.PENDIENTE).count() if puede_cobrar else 0,
    }
