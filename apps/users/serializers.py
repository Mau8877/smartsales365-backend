from rest_framework import serializers
from django.db import transaction
from apps.saas.models import Tienda
from .models import User, Rol, UserProfile, Cliente, Vendedor, Administrador

# --- Serializer para el Modelo Rol ---
class RolSerializer(serializers.ModelSerializer):
    """
    Serializer para listar y gestionar Roles.
    Muestra los campos principales del modelo Rol.
    """
    class Meta:
        model = Rol
        fields = ['id', 'nombre', 'descripcion', 'estado']


# --- Serializers para los Perfiles Específicos (para anidación) ---
# Estos serializers se usarán para anidar DENTRO del UserSerializer.
# No incluyen el campo 'user' para evitar redundancia en la creación.

class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer para el perfil general del usuario (UserProfile)."""
    class Meta:
        model = UserProfile
        exclude = ['user']

class ClienteProfileSerializer(serializers.ModelSerializer):
    """Serializer para el perfil de Cliente."""
    class Meta:
        model = Cliente
        exclude = ['user']

class VendedorProfileSerializer(serializers.ModelSerializer):
    """Serializer para el perfil de Vendedor."""
    class Meta:
        model = Vendedor
        exclude = ['user']

class AdministradorProfileSerializer(serializers.ModelSerializer):
    """Serializer para el perfil de Administrador."""
    class Meta:
        model = Administrador
        exclude = ['user']

# --- Serializer Principal para el Modelo User ---
class UserSerializer(serializers.ModelSerializer):
    """
    Serializer completo para el modelo User.
    - Maneja la creación y actualización anidada de perfiles.
    - Devuelve una representación limpia y útil del usuario y su rol/perfil.
    - Controla la data que se envía para evitar sobrecarga (respuesta a "no mandar 3 tablas").
    """
    # --- Campos de solo lectura para una mejor representación en GET ---
    rol = RolSerializer(read_only=True)
    tienda_nombre = serializers.CharField(source='tienda.nombre', read_only=True, allow_null=True)

    # --- Campos de solo escritura para recibir IDs en POST/PUT ---
    rol_id = serializers.PrimaryKeyRelatedField(
        queryset=Rol.objects.all(), source='rol', write_only=True
    )
    tienda_id = serializers.PrimaryKeyRelatedField(
        queryset=Tienda.objects.all(), source='tienda', required=False, allow_null=True, write_only=True
    )

    # --- Campos de Perfiles Anidados ---
    profile = UserProfileSerializer()
    cliente_profile = ClienteProfileSerializer(required=False, allow_null=True, write_only=True)
    vendedor_profile = VendedorProfileSerializer(required=False, allow_null=True, write_only=True)
    admin_profile = AdministradorProfileSerializer(required=False, allow_null=True, write_only=True)

    class Meta:
        model = User
        fields = [
            'id_usuario', 'email', 'password', 'rol', 'rol_id', 'tienda_id', 'tienda_nombre',
            'is_active', 'fecha_creacion',
            'profile', 'cliente_profile', 'vendedor_profile', 'admin_profile'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
        }

    @transaction.atomic
    def create(self, validated_data):
        """
        Sobrescribe el método create para manejar la creación del usuario
        y sus perfiles anidados de forma atómica.
        """
        profile_data = validated_data.pop('profile')
        cliente_data = validated_data.pop('cliente_profile', None)
        vendedor_data = validated_data.pop('vendedor_profile', None)
        admin_data = validated_data.pop('admin_profile', None)
        rol = validated_data.get('rol')
        
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user, **profile_data)

        if rol:
            if rol.nombre == 'cliente' and cliente_data:
                Cliente.objects.create(user=user, **cliente_data)
            elif rol.nombre == 'vendedor' and vendedor_data:
                Vendedor.objects.create(user=user, **vendedor_data)
            elif rol.nombre == 'admin' and admin_data:
                Administrador.objects.create(user=user, **admin_data)

        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        if profile_data:
            profile_serializer = self.fields['profile']
            profile_instance = instance.profile
            profile_serializer.update(profile_instance, profile_data)
        
        password = validated_data.pop('password', None)
        if password:
            instance.set_password(password)
        
        return super().update(instance, validated_data)
        
    def to_representation(self, instance):
        """
        Controla la representación JSON de salida para mostrar el perfil
        adecuado y limpiar los datos innecesarios.
        """
        representation = super().to_representation(instance)
        rol_nombre = instance.rol.nombre if instance.rol else None

        # Añadimos el perfil correspondiente al rol de forma limpia
        if rol_nombre == 'cliente' and hasattr(instance, 'cliente_profile'):
            representation['perfil_cliente'] = ClienteProfileSerializer(instance.cliente_profile).data
        elif rol_nombre == 'vendedor' and hasattr(instance, 'vendedor_profile'):
            representation['perfil_vendedor'] = VendedorProfileSerializer(instance.vendedor_profile).data
        elif rol_nombre == 'admin' and hasattr(instance, 'admin_profile'):
            representation['perfil_administrador'] = AdministradorProfileSerializer(instance.admin_profile).data

        # Limpiamos los campos de solo escritura de la respuesta JSON
        representation.pop('cliente_profile', None)
        representation.pop('vendedor_profile', None)
        representation.pop('admin_profile', None)
            
        return representation

# --- Serializers para Vistas de Lista/Detalle de Perfiles Específicos ---
# Ideales para endpoints como /api/clientes/ donde se quiere ver todo.

class ClienteDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True) # Anidación controlada
    class Meta:
        model = Cliente
        fields = '__all__'

class VendedorDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta:
        model = Vendedor
        fields = '__all__'

class AdministradorDetailSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta:
        model = Administrador
        fields = '__all__'
