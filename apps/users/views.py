from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.filters import SearchFilter, OrderingFilter
from django.contrib.auth import authenticate
from django.db.models import Q 

from .models import User, Rol, Cliente, Vendedor, Administrador # * ya no es buena práctica
from .serializers import UserSerializer, RolSerializer, ClienteSerializer, VendedorSerializer, AdministradorSerializer 
from apps.auditoria.utils import log_action, get_actor_usuario_from_request
from config.pagination import CustomPageNumberPagination # Necesario para la paginación

# ViewSet para el modelo User
class UserViewSet(viewsets.ModelViewSet):
    """Gestión de usuarios y autenticación (Login, Logout, CRUD, Cambiar Contraseña)."""
    
    queryset = User.objects.all().select_related('rol', 'profile', 'cliente_profile', 'vendedor_profile', 'admin_profile') 
    serializer_class = UserSerializer
   
    pagination_class = CustomPageNumberPagination
    filter_backends = [OrderingFilter, SearchFilter]
    ordering_fields = ['email', 'id_usuario', 'rol__nombre', 'profile__apellido'] 
    search_fields = ['email', 'profile__nombre', 'profile__apellido', 'ci'] 
    
    def get_permissions(self):
        if self.action in ['create', 'login']: 
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        queryset = self.queryset
        rol_nombre = self.request.query_params.get('rol', None)
        if rol_nombre:
            # Uso de __iexact para coincidencia exacta e insensible a mayúsculas/minúsculas
            queryset = queryset.filter(rol__nombre__iexact=rol_nombre) 
        return queryset
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    @action(detail=False, methods=['post'])
    @permission_classes([AllowAny])
    def login(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        if not email or not password:
            return Response({"error": "El correo (email) y la contraseña son requeridos"}, status=status.HTTP_400_BAD_REQUEST)
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.puede_acceder_sistema():
            return Response({"error": "Tu rol no tiene acceso activo al sistema."}, status=status.HTTP_403_FORBIDDEN)
        token, created = Token.objects.get_or_create(user=user)
        log_action(request=request, accion=f"Inicio de sesión del usuario (id:{user.id_usuario})", objeto=f"Usuario: {email}", usuario=user)
        return Response({
            "message": "Login exitoso",
            "usuario_id": user.id_usuario,
            "token": token.key,
            "rol": user.rol.nombre if user.rol else 'Sin Rol', 
            "nombre_completo": f"{user.profile.nombre} {user.profile.apellido}" if hasattr(user, 'profile') else 'N/A'
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    @permission_classes([IsAuthenticated])
    def logout(self, request):
        try:
            Token.objects.filter(user=request.user).delete()
            log_action(request=request, accion=f"Cierre de sesión del usuario (id:{request.user.id_usuario})", objeto=f"Usuario: {request.user.email}", usuario=request.user)
            return Response({"message": "Cierre de sesión exitoso"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Ocurrió un error al cerrar sesión: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    @action(detail=True, methods=['post'])
    def cambiar_password(self, request, pk=None):
        user = self.get_object() 
        nuevo_password = request.data.get('password')
        if not nuevo_password:
            return Response({'error': 'La nueva contraseña es requerida'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(nuevo_password)
        user.save()
        Token.objects.filter(user=user).delete()
        log_action(request=request, accion=f"Cambió la contraseña del usuario (id:{user.id_usuario})", objeto=f"Usuario: {user.email}", usuario=request.user)
        return Response({'message': 'Contraseña actualizada correctamente. Requiere nuevo login.'}, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        user_obj = serializer.save()
        user_nombre = user_obj.profile.nombre if hasattr(user_obj, 'profile') else user_obj.email
        actor = get_actor_usuario_from_request(self.request)
        log_action(request=self.request, accion=f"Creó usuario {user_nombre} (id:{user_obj.id_usuario})", objeto=f"Usuario: {user_nombre} (id:{user_obj.id_usuario})", usuario=actor)

    def perform_destroy(self, instance):
        nombre = instance.email
        pk = instance.pk
        actor = get_actor_usuario_from_request(self.request)
        instance.delete()
        log_action(request=self.request, accion=f"Eliminó usuario {nombre} (id:{pk})", objeto=f"Usuario: {nombre} (id:{pk})", usuario=actor)

    def perform_update(self, serializer):
        user_obj = serializer.save() 
        user_nombre = user_obj.profile.nombre if hasattr(user_obj, 'profile') else user_obj.email
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request,
            accion=f"Actualizó usuario {user_nombre} (id:{user_obj.id_usuario})",
            objeto=f"Usuario: {user_nombre} (id:{user_obj.id_usuario})",
            usuario=actor
        )

# ViewSet para el modelo Rol
class RolViewSet(viewsets.ModelViewSet):
    """Gestión de Roles del sistema."""
    queryset = Rol.objects.all().order_by('nombre')
    serializer_class = RolSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['nombre', 'estado']

    def perform_create(self, serializer):
        rol_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request, 
            accion=f"Creó Rol {rol_obj.nombre}", 
            objeto=f"Rol: {rol_obj.nombre} (id:{rol_obj.id}) por {actor.email}", 
            usuario=actor
        )

    def perform_destroy(self, instance):
        nombre = instance.nombre
        pk = instance.pk
        actor = get_actor_usuario_from_request(self.request)
        instance.delete()
        log_action(
            request=self.request, 
            accion=f"Eliminó Rol {nombre} (id:{pk})", 
            objeto=f"Rol: {nombre} (id:{pk}) por {actor.email}", 
            usuario=actor
        )

    def perform_update(self, serializer):
        rol_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request,
            accion=f"Actualizó Rol {rol_obj.nombre}",
            objeto=f"Rol: {rol_obj.nombre} (id:{rol_obj.id}) por {actor.email}",
            usuario=actor
        )

# ViewSet para el modelo Cliente
class ClienteViewSet(viewsets.ModelViewSet):
    """Gestión de perfiles de Clientes."""
    queryset = Cliente.objects.all().select_related('user', 'user__profile')
    serializer_class = ClienteSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nivel_fidelidad', 'user__email', 'user__profile__nombre', 'user__profile__apellido']
    ordering_fields = ['nivel_fidelidad', 'puntos_acumulados', 'user__email']

    def perform_create(self, serializer):
        cliente_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request, 
            accion=f"Creó perfil de Cliente para {cliente_obj.user.email} (id:{cliente_obj.id})", 
            objeto=f"Cliente: {cliente_obj.user.email} (id:{cliente_obj.id}) Creado por: {actor.email}", 
            usuario=actor
        )

    def perform_destroy(self, instance):
        email = instance.user.email 
        pk = instance.pk
        actor = get_actor_usuario_from_request(self.request)
        instance.delete()
        log_action(
            request=self.request,
            accion=f"Eliminó perfil de Cliente {email} (id:{pk})",
            objeto=f"Cliente: {email} (id:{pk}) Eliminado por: {actor.email}",
            usuario=actor
        )

    def perform_update(self, serializer):
        cliente_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request,
            accion=f"Actualizó perfil de Cliente {cliente_obj.user.email}",
            objeto=f"Cliente: {cliente_obj.user.email} (id:{cliente_obj.id}) Actualizado por: {actor.email}",
            usuario=actor
        )

# ViewSet para el modelo Vendedor
class VendedorViewSet(viewsets.ModelViewSet):
    """Gestión de perfiles de Vendedores."""
    queryset = Vendedor.objects.all().select_related('user', 'user__profile')
    serializer_class = VendedorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['user__email', 'user__profile__nombre', 'tasa_comision']
    ordering_fields = ['ventas_realizadas', 'tasa_comision', 'fecha_contratacion']

    def perform_create(self, serializer):
        vendedor_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request, 
            accion=f"Creó perfil de Vendedor para {vendedor_obj.user.email}", 
            objeto=f"Vendedor: {vendedor_obj.user.email} (id:{vendedor_obj.id}) Creado por: {actor.email}", 
            usuario=actor
        )

    def perform_destroy(self, instance):
        email = instance.user.email 
        pk = instance.pk
        actor = get_actor_usuario_from_request(self.request)
        instance.delete()
        log_action(
            request=self.request,
            accion=f"Eliminó perfil de Vendedor {email} (id:{pk})",
            objeto=f"Vendedor: {email} (id:{pk}) Eliminado por: {actor.email}",
            usuario=actor
        )

    def perform_update(self, serializer):
        vendedor_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request,
            accion=f"Actualizó perfil de Vendedor {vendedor_obj.user.email}",
            objeto=f"Vendedor: {vendedor_obj.user.email} (id:{vendedor_obj.id}) Actualizado por: {actor.email}",
            usuario=actor
        )

# ViewSet para el modelo Administrador
class AdministradorViewSet(viewsets.ModelViewSet):
    """Gestión de perfiles de Administradores."""
    queryset = Administrador.objects.all().select_related('user', 'user__profile')
    serializer_class = AdministradorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['departamento', 'user__email', 'user__profile__nombre']
    ordering_fields = ['departamento', 'fecha_contratacion']

    def perform_create(self, serializer):
        admin_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request, 
            accion=f"Creó perfil de Administrador para {admin_obj.user.email}", 
            objeto=f"Administrador: {admin_obj.user.email} (id:{admin_obj.id}) Creado por: {actor.email}", 
            usuario=actor
        )

    def perform_destroy(self, instance):
        email = instance.user.email 
        pk = instance.pk
        actor = get_actor_usuario_from_request(self.request)
        instance.delete()
        log_action(
            request=self.request,
            accion=f"Eliminó perfil de Administrador {email} (id:{pk})",
            objeto=f"Administrador: {email} (id:{pk}) Eliminado por: {actor.email}",
            usuario=actor
        )

    def perform_update(self, serializer):
        admin_obj = serializer.save()
        actor = get_actor_usuario_from_request(self.request)
        log_action(
            request=self.request,
            accion=f"Actualizó perfil de Administrador {admin_obj.user.email}",
            objeto=f"Administrador: {admin_obj.user.email} (id:{admin_obj.id}) Actualizado por: {actor.email}",
            usuario=actor
        )