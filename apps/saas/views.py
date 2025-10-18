from django.shortcuts import render
from rest_framework import viewsets, permissions, mixins
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import PlanSuscripcion, Tienda, PagoSuscripcion
from .serializers import (
    PlanSuscripcionSerializer, TiendaSerializer, TiendaDetailSerializer, PagoSuscripcionSerializer
)
from apps.users.views import IsSuperAdmin
from config.pagination import CustomPageNumberPagination

# --- ViewSets de la Aplicación SaaS ---

class PlanSuscripcionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Endpoint para listar los planes de suscripción disponibles.
    Solo permite la lectura (listado).
    """
    queryset = PlanSuscripcion.objects.all().order_by('precio_mensual')
    serializer_class = PlanSuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]

class TiendaViewSet(viewsets.ModelViewSet):
    """
    Gestión de Tiendas (Tenants).
    - SuperAdmin: CRUD completo.
    - Admin: Solo puede ver su propia tienda.
    """
    queryset = Tienda.objects.all().select_related('plan', 'admin_contacto', 'admin_contacto__profile')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nombre', 'plan__nombre', 'admin_contacto__email']
    ordering_fields = ['nombre', 'fecha_inicio_servicio', 'estado']

    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return TiendaDetailSerializer
        return TiendaSerializer

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return self.queryset.none()

        if user.rol and user.rol.nombre == 'superAdmin':
            return self.queryset
        if user.tienda:
            return self.queryset.filter(id=user.tienda.id)
        return self.queryset.none()

    def get_permissions(self):
        # Solo el SuperAdmin puede crear, modificar o eliminar tiendas.
        if self.action not in ['list', 'retrieve']:
            self.permission_classes = [IsSuperAdmin]
        return super().get_permissions()

class PagoSuscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Endpoint de solo lectura para los pagos de suscripción.
    - SuperAdmin: Ve todos los pagos.
    - Admin: Ve solo los pagos de su tienda.
    """
    queryset = PagoSuscripcion.objects.all().select_related('tienda', 'plan_pagado')
    serializer_class = PagoSuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [OrderingFilter]
    ordering_fields = ['-fecha_emision', 'estado']

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return self.queryset.none()

        if user.rol and user.rol.nombre == 'superAdmin':
            return self.queryset
        if user.tienda:
            return self.queryset.filter(tienda=user.tienda)
        return self.queryset.none()

