from django.shortcuts import render
from rest_framework import viewsets, permissions
from rest_framework.filters import OrderingFilter, SearchFilter
from .models import Bitacora
from .serializers import BitacoraSerializer
from config.pagination import CustomPageNumberPagination

class IsAdminOrSuperAdmin(permissions.BasePermission):
    """Permiso para solo permitir acceso a usuarios con rol Admin o SuperAdmin."""
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.rol.nombre in ['admin', 'superAdmin']

class BitacoraViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para la lectura de registros de auditoría.
    Usa ReadOnlyModelViewSet porque los logs no deben ser modificados.
    """
    queryset = Bitacora.objects.all()
    serializer_class = BitacoraSerializer
    pagination_class = CustomPageNumberPagination

    permission_classes = [IsAdminOrSuperAdmin] 

    filter_backends = [OrderingFilter, SearchFilter]
    ordering_fields = ['timestamp', 'user__email'] 
    search_fields = ['accion', 'objeto', 'user__email'] 

    def get_queryset(self):
        queryset = Bitacora.objects.all().select_related('user', 'user__rol', 'user__profile')
        # Filtro opcional: filtrar por usuario (ej: ?user_id=5)
        user_id = self.request.query_params.get('user_id', None)
        if user_id:
            queryset = queryset.filter(user_id=user_id)
            
        return queryset