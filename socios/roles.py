"""Roles del sistema y control de acceso a cada pantalla.

Los roles son grupos de Django (Usuarios -> Grupos en el panel de administración).
Surgen del relevamiento: Secretaría, Tesorería, Comisión directiva y Socios.

    Secretaría          -> todo: socios, cuotas, cobros, informes y accesos al portal
    Tesorería           -> cobros, avisos de pago, cuotas e informes (ve socios, no los edita)
    Comisión directiva  -> solo consulta: panel, listados e informes
    Socio               -> solo su portal: su estado de cuenta, comprobantes y avisos de pago

Principio de mínimo privilegio: cada usuario tiene solo los permisos que necesita.
El cargo en la comisión directiva (Socio.cargo) NO da permisos: el acceso se asigna aparte.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

SECRETARIA = "Secretaría"
TESORERIA = "Tesorería"
DIRECTIVA = "Comisión directiva"
SOCIO = "Socio"
ROLES = [SECRETARIA, TESORERIA, DIRECTIVA, SOCIO]

# Grupos de roles según la acción
PERSONAL = (SECRETARIA, TESORERIA, DIRECTIVA)   # pueden consultar la gestión
COBRAN = (SECRETARIA, TESORERIA)                # pueden cobrar y generar cuotas
GESTIONAN_SOCIOS = (SECRETARIA,)                # pueden dar de alta, editar y dar de baja


def roles_de(usuario):
    """Nombres de los roles del usuario (se guardan en el objeto para no repetir la consulta)."""
    if not usuario.is_authenticated:
        return set()
    if not hasattr(usuario, "_roles_asocia"):
        usuario._roles_asocia = set(usuario.groups.values_list("name", flat=True))
    return usuario._roles_asocia


def tiene_rol(usuario, *roles):
    if usuario.is_authenticated and usuario.is_superuser:
        return True  # el administrador del sistema puede todo
    return bool(roles_de(usuario) & set(roles))


def es_socio(usuario):
    """Usuario del portal: tiene rol Socio y ningún rol de gestión."""
    return SOCIO in roles_de(usuario) and not tiene_rol(usuario, *PERSONAL)


def _sin_permiso(request):
    # Un socio que entra a una pantalla de gestión vuelve a su portal; el resto ve "acceso denegado"
    if es_socio(request.user):
        return redirect("socios:portal")
    raise PermissionDenied


def rol_requerido(*roles):
    """Decorador para vistas-función: exige iniciar sesión y tener alguno de los roles."""
    def decorador(vista):
        @login_required
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not tiene_rol(request.user, *roles):
                return _sin_permiso(request)
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


class RolRequeridoMixin(LoginRequiredMixin):
    """Lo mismo para vistas basadas en clases: se indica `roles = (...)`."""
    roles = PERSONAL

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not tiene_rol(request.user, *self.roles):
            return _sin_permiso(request)
        return super().dispatch(request, *args, **kwargs)
