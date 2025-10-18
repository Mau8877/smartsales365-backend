from rest_framework import viewsets, permissions, status, mixins
from rest_framework.response import Response
from django.db import transaction
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import PlanSuscripcion, Tienda, PagoSuscripcion
from .serializers import (
    PlanSuscripcionSerializer, TiendaSerializer, PagoSuscripcionSerializer,
    TiendaDetailSerializer, RegistroSerializer
)
from apps.users.models import User, UserProfile, Rol
from apps.auditoria.utils import log_action
from config.pagination import CustomPageNumberPagination
from apps.users.views import IsSuperAdmin # Importamos desde users/views

# --- ViewSets ---

class PlanSuscripcionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """API para listar los planes de suscripción disponibles."""
    queryset = PlanSuscripcion.objects.all().order_by('precio_mensual')
    serializer_class = PlanSuscripcionSerializer
    permission_classes = [permissions.AllowAny] # Planes son públicos para que nuevos clientes los vean

class TiendaViewSet(viewsets.ModelViewSet):
    """API de gestión interna para Tiendas. SuperAdmin tiene control total."""
    queryset = Tienda.objects.all().select_related('plan', 'admin_contacto', 'admin_contacto__profile')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nombre', 'plan__nombre', 'admin_contacto__email']
    ordering_fields = ['nombre', 'fecha_inicio_servicio', 'estado']
    
    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return TiendaDetailSerializer
        return TiendaSerializer
    
    def get_permissions(self):
        if self.action not in ['list', 'retrieve']:
            self.permission_classes = [IsSuperAdmin]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin':
            return self.queryset
        if user.tienda:
            return self.queryset.filter(id=user.tienda.id)
        return self.queryset.none()

class PagoSuscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    """API de solo lectura para los pagos."""
    queryset = PagoSuscripcion.objects.all()
    serializer_class = PagoSuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin':
            return self.queryset
        if user.tienda:
            return self.queryset.filter(tienda=user.tienda)
        return self.queryset.none()

# --- ViewSet para el Registro Público ---

class RegistroViewSet(viewsets.ViewSet):
    """Endpoint público para el registro de una nueva tienda y su administrador."""
    permission_classes = [permissions.AllowAny]

    def create(self, request):
        serializer = RegistroSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        
        if User.objects.filter(email=data['admin_email']).exists():
            return Response({"error": "Este correo electrónico ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                rol_admin, _ = Rol.objects.get_or_create(nombre='admin', defaults={'descripcion': 'Administrador de una tienda.'})
                admin_user = User.objects.create_user(email=data['admin_email'], password=data['admin_password'], rol=rol_admin)
                UserProfile.objects.create(user=admin_user, nombre=data['admin_nombre'], apellido=data['admin_apellido'], ci=data['admin_ci'], telefono=data.get('admin_telefono', ''))
                plan = PlanSuscripcion.objects.get(pk=data['plan_id'])
                nueva_tienda = Tienda.objects.create(plan=plan, nombre=data['tienda_nombre'], admin_contacto=admin_user)
                admin_user.tienda = nueva_tienda
                admin_user.save()
                log_action(request=request, accion=f"Registro de nueva tienda '{nueva_tienda.nombre}' y admin '{admin_user.email}'.", usuario=admin_user)
        except Exception as e:
            return Response({"error": f"Ocurrió un error inesperado: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "¡Tienda y administrador creados exitosamente!"}, status=status.HTTP_201_CREATED)

