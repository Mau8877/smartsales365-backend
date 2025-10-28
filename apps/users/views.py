from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.authtoken.models import Token
from rest_framework.filters import SearchFilter, OrderingFilter
from django.contrib.auth import authenticate, login
from django.db.models import Q
from .utils import get_user_tienda

from .models import User, Rol, Cliente, Vendedor, Administrador, UserProfile
from .serializers import (
    UserSerializer, RolSerializer, ClienteDetailSerializer, 
    VendedorDetailSerializer, AdministradorDetailSerializer,
    UserProfileUpdateSerializer, ChangePasswordSerializer,
    UserPhotoSerializer,
)
from apps.auditoria.utils import log_action
from config.pagination import CustomPageNumberPagination

class IsSuperAdmin(permissions.BasePermission):
    """Permite el acceso solo a usuarios con el rol de superAdmin."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol and request.user.rol.nombre == 'superAdmin'

class TenantAwareViewSet(viewsets.ModelViewSet):
    """
    Un ViewSet base que filtra el queryset para la tienda del usuario actual.
    El superAdmin puede ver todos los datos.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_authenticated: return queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return queryset
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(tienda=tienda_actual)
        return queryset.none()

class UserViewSet(viewsets.ModelViewSet):
    """Gestión de usuarios y autenticación, adaptado para SaaS."""
    queryset = User.objects.all().select_related('rol', 'profile').prefetch_related('admin_profile__tienda', 'vendedor_profile__tienda')
    serializer_class = UserSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [OrderingFilter, SearchFilter]
    ordering_fields = ['email', 'rol__nombre', 'profile__apellido'] 
    search_fields = ['email', 'profile__nombre', 'profile__apellido'] 
    
    def get_permissions(self):
        if self.action in ['create', 'login']:
            return [AllowAny()]
        if self.action in ['me', 'logout', 'cambiar_password', 'change_my_password']:
             return [IsAuthenticated()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_authenticated: return queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return queryset
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(
                Q(admin_profile__tienda=tienda_actual) |
                Q(vendedor_profile__tienda=tienda_actual) |
                Q(tiendas_como_cliente=tienda_actual) 
            ).distinct()
        return queryset.none()
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == 'create':
            actor = self.request.user
            if actor.is_authenticated and actor.rol.nombre != 'superAdmin':
                context['tienda_forzada'] = get_user_tienda(actor)
        return context

    # --- ACCIÓN "ME" (GET Y PATCH PARA DATOS DE PERFIL) ---
    @action(
        detail=False, 
        methods=['get', 'patch'], 
        permission_classes=[IsAuthenticated],
        url_path='me'  # /api/users/me/
    )
    def me(self, request, *args, **kwargs):
        """
        Endpoint para OBTENER (GET) o ACTUALIZAR (PATCH) 
        el perfil del usuario actualmente autenticado.
        (Email y datos de UserProfile).
        """
        user = request.user 

        if request.method == 'GET':
            # GET: Devuelve el perfil completo del usuario
            serializer = self.get_serializer(user, context=self.get_serializer_context())
            return Response(serializer.data, status=status.HTTP_200_OK)

        if request.method == 'PATCH':
            # PATCH: Actualiza usando el serializador restringido
            serializer = UserProfileUpdateSerializer(
                user, 
                data=request.data, 
                partial=True,
                context=self.get_serializer_context()
            )

            if serializer.is_valid():
                # Validación de email duplicado
                new_email = serializer.validated_data.get('email')
                if new_email and new_email != user.email:
                    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                        return Response(
                            {'email': ['Este correo electrónico ya está en uso.']},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                
                user_obj = serializer.save()
                user_nombre = user_obj.profile.nombre if hasattr(user_obj, 'profile') else user_obj.email
                
                log_action(
                    request=request, 
                    accion="Actualizó su propio perfil (datos)", 
                    objeto=f"Usuario: {user_nombre} (id:{user_obj.id_usuario})", 
                    usuario=user
                )
                
                # Devolvemos los datos actualizados usando el serializador completo
                full_data_serializer = self.get_serializer(user_obj, context=self.get_serializer_context())
                return Response(full_data_serializer.data, status=status.HTTP_200_OK)
            
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- CAMBIAR MI PROPIA CONTRASEÑA ---
    @action(
        detail=False, 
        methods=['post'], 
        permission_classes=[IsAuthenticated],
        url_path='me/change-password' # /api/users/me/change-password/
    )
    def change_my_password(self, request, *args, **kwargs):
        """
        Permite al usuario autenticado cambiar su propia contraseña.
        Requiere 'old_password' y 'new_password'.
        """
        user = request.user
        
        # Pasamos el 'request' al contexto para que el serializer pueda acceder al 'user'
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            # El serializador ya validó la 'old_password'.
            # Ahora solo establecemos la nueva.
            new_password = serializer.validated_data['new_password']
            user.set_password(new_password)
            user.save()
            
            # Invalidar todos los tokens (buena práctica de seguridad)
            Token.objects.filter(user=user).delete()
            
            # Registrar en auditoría
            log_action(
                request=request,
                accion="Cambió su propia contraseña",
                objeto=f"Usuario: {user.email} (id:{user.id_usuario})",
                usuario=user
            )
            
            return Response(
                {'message': 'Contraseña actualizada exitosamente. Se ha cerrado la sesión en todos los dispositivos.'}, 
                status=status.HTTP_200_OK
            )
        
        # Si el serializador no es válido (ej. old_password incorrecta)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- CAMBIAR CONTRASEÑA DE OTRO (ADMIN) ---
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def cambiar_password(self, request, pk=None):
        """
        Esta acción permite a un usuario
        cambiar la contraseña de OTRO usuario por ID.
        No requiere la contraseña antigua.
        """
        user = self.get_object() 
        nuevo_password = request.data.get('password')
        if not nuevo_password:
            return Response({'error': 'La nueva contraseña es requerida'}, status=status.HTTP_400_BAD_REQUEST)
        
        # NOTA: Sería bueno añadir un permiso aquí
        # if not request.user.is_staff:
        #    return Response({'error': 'No autorizado'}, status=status.HTTP_403_FORBIDDEN)

        user.set_password(nuevo_password)
        user.save()
        Token.objects.filter(user=user).delete()
        log_action(request=request, accion=f"Cambió la contraseña del usuario (id:{user.id_usuario})", objeto=f"Usuario: {user.email}", usuario=request.user)
        return Response({'message': 'Contraseña actualizada. Se requiere un nuevo login.'}, status=status.HTTP_200_OK)

    # --- (ACCIÓN FINAL) SUBIR FOTO DE PERFIL A CLOUDINARY ---
    @action(
        detail=False, 
        methods=['post'], 
        permission_classes=[IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser], # Espera 'multipart/form-data'
        url_path='me/upload-photo'
    )

    @action(
        detail=False, 
        methods=['post'], 
        permission_classes=[IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser],
        url_path='me/upload-photo'
    )
    def upload_my_photo(self, request, *args, **kwargs):
        """
        Sube o actualiza la foto de perfil del usuario a Cloudinary.
        """
        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            return Response(
                {"error": "El usuario no tiene un perfil."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # Verifica que se haya enviado un archivo
        if 'foto_perfil' not in request.FILES:
            return Response(
                {"error": "No se proporcionó ninguna imagen."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = UserPhotoSerializer(profile, data=request.data, partial=True)

        if serializer.is_valid():
            # Guarda la imagen (Cloudinary se encarga de la subida)
            updated_profile = serializer.save()
            
            # Log de la acción
            log_action(
                request=request, 
                accion="Actualizó su foto de perfil", 
                objeto=f"Usuario: {request.user.email}", 
                usuario=request.user
            )
            
            # Devuelve la respuesta con la URL
            return Response(
                {
                    "message": "Foto de perfil actualizada exitosamente",
                    "foto_perfil": serializer.data['foto_perfil']
                }, 
                status=status.HTTP_200_OK
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        user_obj = serializer.save()
        user_nombre = user_obj.profile.nombre if hasattr(user_obj, 'profile') else user_obj.email
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre}" if actor.is_authenticated and tienda_actor else ""
        log_action(request=self.request, accion=f"Creó usuario {user_nombre}{tienda_info}", objeto=f"Usuario: {user_nombre} (id:{user_obj.id_usuario})", usuario=actor if actor.is_authenticated else None)

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        if not email or not password:
            return Response({"error": "El correo (email) y la contraseña son requeridos"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=email, password=password)
        if user:
            if not user.puede_acceder_sistema():
                return Response({"error": "Tu rol no tiene acceso activo al sistema."}, status=status.HTTP_403_FORBIDDEN)

            login(request, user)
            token, _ = Token.objects.get_or_create(user=user)
            
            tienda_actual = get_user_tienda(user)
            if user.rol and user.rol.nombre == 'superAdmin':
                loginfo = " (Global - SuperAdmin)"
            elif tienda_actual:
                loginfo = f" en Tienda: {tienda_actual.nombre} (ID: {tienda_actual.id})"
            else:
                loginfo = ""

            log_action(request, f"Inicio de sesión{loginfo}", f"Usuario: {email}", user)

            return Response({
                "message": "Login exitoso",
                "token": token.key,
                "user_id": user.id_usuario,
                "rol": user.rol.nombre if user.rol else None,
                "tienda_id": tienda_actual.id if tienda_actual else None,
                "nombre_completo": f"{user.profile.nombre} {user.profile.apellido}" if hasattr(user, 'profile') else 'N/A'
            }, status=status.HTTP_200_OK)
        
        return Response({"error": "Credenciales inválidas"}, status=status.HTTP_401_UNAUTHORIZED)
    
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def logout(self, request):
        user = request.user
        tienda_actual = get_user_tienda(user)

        if user.rol and user.rol.nombre == 'superAdmin':
            loginfo = " (Global - SuperAdmin)"
        elif tienda_actual:
            loginfo = f" en Tienda: {tienda_actual.nombre} (ID: {tienda_actual.id})"
        else:
            loginfo = ""

        log_action(request=request, accion=f"Cierre de sesión{loginfo}", objeto=f"Usuario: {user.email}", usuario=user)
        Token.objects.filter(user=user).delete()
        return Response({"message": "Cierre de sesión exitoso"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsSuperAdmin])
    def cambiar_password(self, request, pk=None):
        user = self.get_object() 
        nuevo_password = request.data.get('password')
        if not nuevo_password:
            return Response({'error': 'La nueva contraseña es requerida'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(nuevo_password)
        user.save()
        Token.objects.filter(user=user).delete()
        log_action(request=request, accion=f"Cambió la contraseña del usuario (id:{user.id_usuario})", objeto=f"Usuario: {user.email}", usuario=request.user)
        return Response({'message': 'Contraseña actualizada. Se requiere un nuevo login.'}, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        nombre = instance.email
        pk = instance.pk
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" de Tienda: {tienda_actor.nombre}" if actor.is_authenticated and tienda_actor else ""
        instance.delete()
        log_action(request=self.request, accion=f"Eliminó usuario {nombre} (id:{pk}){tienda_info}", objeto=f"Usuario: {nombre} (id:{pk})", usuario=actor)

    def perform_update(self, serializer):
        user_obj = serializer.save() 
        user_nombre = user_obj.profile.nombre if hasattr(user_obj, 'profile') else user_obj.email
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre}" if actor.is_authenticated and tienda_actor else ""
        log_action(request=self.request, accion=f"Actualizó usuario {user_nombre} (id:{user_obj.id_usuario}){tienda_info}", objeto=f"Usuario: {user_nombre} (id:{user_obj.id_usuario})", usuario=actor)


class RolViewSet(viewsets.ModelViewSet):
    """Gestión de Roles del sistema (Solo para SuperAdmin)."""
    queryset = Rol.objects.all().order_by('nombre')
    serializer_class = RolSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    filter_backends = [SearchFilter]
    search_fields = ['nombre']

    def perform_create(self, serializer):
        rol_obj = serializer.save()
        actor = self.request.user
        log_action(
            request=self.request, 
            accion=f"Creó Rol {rol_obj.nombre}", 
            objeto=f"Rol: {rol_obj.nombre} (id:{rol_obj.id})", 
            usuario=actor
        )

    def perform_destroy(self, instance):
        nombre = instance.nombre
        pk = instance.pk
        actor = self.request.user
        instance.delete()
        log_action(
            request=self.request, 
            accion=f"Eliminó Rol {nombre} (id:{pk})", 
            objeto=f"Rol: {nombre} (id:{pk})", 
            usuario=actor
        )

    def perform_update(self, serializer):
        rol_obj = serializer.save()
        actor = self.request.user
        log_action(
            request=self.request, 
            accion=f"Actualizó Rol {rol_obj.nombre}", 
            objeto=f"Rol: {rol_obj.nombre} (id:{rol_obj.id})", 
            usuario=actor
        )


class ClienteViewSet(viewsets.ModelViewSet):
    """Gestión de perfiles de Clientes."""
    queryset = Cliente.objects.all().select_related('user__profile', 'user__rol')
    serializer_class = ClienteDetailSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nivel_fidelidad', 'user__email', 'user__profile__nombre', 'user__profile__apellido']
    ordering_fields = ['nivel_fidelidad', 'puntos_acumulados', 'user__email']

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_authenticated: return queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return queryset
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(user__tiendas_como_cliente=tienda_actual)
        return queryset.none()


class VendedorViewSet(TenantAwareViewSet):
    """Gestión de perfiles de Vendedores, filtrado por tienda."""
    queryset = Vendedor.objects.all().select_related('user__profile', 'user__rol', 'tienda')
    serializer_class = VendedorDetailSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['user__email', 'user__profile__nombre', 'tasa_comision']
    ordering_fields = ['ventas_realizadas', 'tasa_comision', 'fecha_contratacion']

    def perform_create(self, serializer):
        vendedor_obj = serializer.save()
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        log_action(request=self.request, accion=f"Creó perfil de Vendedor para {vendedor_obj.user.email}{tienda_info}", objeto=f"Vendedor: {vendedor_obj.user.email}", usuario=actor)

    def perform_destroy(self, instance):
        email = instance.user.email 
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" de Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        instance.delete()
        log_action(request=self.request, accion=f"Eliminó perfil de Vendedor {email}{tienda_info}", objeto=f"Vendedor: {email}", usuario=actor)

    def perform_update(self, serializer):
        vendedor_obj = serializer.save()
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        log_action(request=self.request, accion=f"Actualizó perfil de Vendedor {vendedor_obj.user.email}{tienda_info}", objeto=f"Vendedor: {vendedor_obj.user.email}", usuario=actor)


class AdministradorViewSet(TenantAwareViewSet):
    """Gestión de perfiles de Administradores, filtrado por tienda."""
    queryset = Administrador.objects.all().select_related('user__profile', 'user__rol', 'tienda')
    serializer_class = AdministradorDetailSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['departamento', 'user__email', 'user__profile__nombre']
    ordering_fields = ['departamento', 'fecha_contratacion']

    def perform_create(self, serializer):
        admin_obj = serializer.save()
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        log_action(request=self.request, accion=f"Creó perfil de Admin para {admin_obj.user.email}{tienda_info}", objeto=f"Administrador: {admin_obj.user.email}", usuario=actor)

    def perform_destroy(self, instance):
        email = instance.user.email
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" de Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        instance.delete()
        log_action(request=self.request, accion=f"Eliminó perfil de Admin {email}{tienda_info}", objeto=f"Administrador: {email}", usuario=actor)

    def perform_update(self, serializer):
        admin_obj = serializer.save()
        actor = self.request.user
        tienda_actor = get_user_tienda(actor)
        tienda_info = f" en Tienda: {tienda_actor.nombre} (ID: {tienda_actor.id})" if tienda_actor else ""
        log_action(request=self.request, accion=f"Actualizó perfil de Admin {admin_obj.user.email}{tienda_info}", objeto=f"Administrador: {admin_obj.user.email}", usuario=actor)
