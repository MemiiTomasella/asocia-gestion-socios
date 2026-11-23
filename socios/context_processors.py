"""Variables disponibles en todas las plantillas."""
from django.conf import settings


def institucion(request):
    """Nombre de la institución que usa Asocia (se configura con la variable INSTITUCION_NOMBRE)."""
    return {"institucion_nombre": settings.INSTITUCION_NOMBRE}
