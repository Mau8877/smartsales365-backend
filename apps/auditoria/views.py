from rest_framework import viewsets, permissions
from rest_framework.filters import OrderingFilter, SearchFilter
from .models import Bitacora
from .serializers import BitacoraSerializer
from config.pagination import CustomPageNumberPagination

class IsAdminOrSuperAdmin(permissions.BasePermission):
    """Permiso para solo permitir acceso a usuarios con rol Admin o SuperAdmin."""
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if hasattr(user, 'rol') and user.rol:
            return user.rol.nombre in ['admin', 'superAdmin']
        return False

class BitacoraViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para la lectura de registros de auditoría (protegido)."""
    queryset = Bitacora.objects.all()
    serializer_class = BitacoraSerializer
    pagination_class = CustomPageNumberPagination
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]
    filter_backends = [OrderingFilter, SearchFilter]
    ordering_fields = ['timestamp', 'user__email', 'tienda__nombre']
    search_fields = ['accion', 'objeto', 'user__email', 'tienda__nombre']

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return self.queryset.none()

        queryset = super().get_queryset().select_related('user', 'user__rol', 'user__profile', 'tienda')
        
        # El superAdmin ve todo
        if user.rol and user.rol.nombre == 'superAdmin':
            return queryset
        
        # Un admin solo ve los logs de su tienda
        if user.tienda:
            return queryset.filter(tienda=user.tienda)
        
        # Si no es superAdmin y no tiene tienda, no ve nada
        return queryset.none()

