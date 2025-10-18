from django.db import models
from apps.users.models import User 

from .models import Bitacora 
from django.conf import settings 

def get_client_ip(request):
    """
    Obtiene la IP del cliente desde el request.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_actor_usuario_from_request(request):
    """
    Intenta obtener el usuario actor (objeto User) desde el request.
    Retorna el objeto User si está autenticado, o None.
    """
    try:
        if hasattr(request, 'user') and request.user.is_authenticated:
            return request.user
        return None
    except:
        return None


def log_action(request, accion, objeto=None, usuario=None):
    """
    Registra una acción en la bitácora.
    """
    try:
        ip = get_client_ip(request)
        if usuario is None:
            usuario = get_actor_usuario_from_request(request)
        Bitacora.objects.create(
            user=usuario,
            accion=accion,
            ip=ip,
            objeto=objeto
        )
    except Exception as e:
        print(f"Error al registrar en bitácora: {e}")