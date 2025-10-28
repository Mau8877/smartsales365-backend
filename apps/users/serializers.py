from rest_framework import serializers
from django.db import transaction
from apps.saas.models import Tienda
from .models import User, Rol, UserProfile, Cliente, Vendedor, Administrador

# --- Serializers de base (sin cambios) ---
class RolSerializer(serializers.ModelSerializer):
    class Meta: 
        model = Rol; 
        fields = ['id', 'nombre', 'descripcion', 'estado']

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta: 
        model = UserProfile; 
        exclude = ['user']

# --- Serializers de Perfil para ESCRITURA (usados en la creación anidada) ---
class VendedorProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Vendedor; fields = ['fecha_contratacion', 'tasa_comision']

class AdministradorProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Administrador; fields = ['departamento', 'fecha_contratacion']

class ClienteProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Cliente; fields = ['nivel_fidelidad', 'puntos_acumulados']

# --- Serializer Principal de User (corregido) ---
class UserSerializer(serializers.ModelSerializer):
    rol_id = serializers.PrimaryKeyRelatedField(queryset=Rol.objects.all(), source='rol', write_only=True)
    rol = RolSerializer(read_only=True)
    profile = UserProfileSerializer()
    tienda_id = serializers.PrimaryKeyRelatedField(queryset=Tienda.objects.all(), required=False, allow_null=True, write_only=True, source='tienda')

    # Perfiles de solo escritura
    vendedor_profile = VendedorProfileWriteSerializer(required=False, allow_null=True)
    admin_profile = AdministradorProfileWriteSerializer(required=False, allow_null=True)
    cliente_profile = ClienteProfileWriteSerializer(required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'id_usuario', 'email', 'password', 'rol', 'rol_id', 'tienda_id', 'is_active', 
            'fecha_creacion', 'profile', 'vendedor_profile', 'admin_profile', 'cliente_profile'
        ]
        extra_kwargs = {'password': {'write_only': True}}

    @transaction.atomic
    def create(self, validated_data):
        profile_data = validated_data.pop('profile')
        rol = validated_data.get('rol')
        tienda = validated_data.pop('tienda', None) or self.context.get('tienda_forzada')
        
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user, **profile_data)

        if rol:
            if rol.nombre == 'vendedor':
                if not tienda: raise serializers.ValidationError("Un Vendedor debe estar asociado a una tienda.")
                Vendedor.objects.create(user=user, tienda=tienda, **(validated_data.pop('vendedor_profile', None) or {}))
            elif rol.nombre == 'admin':
                if not tienda: raise serializers.ValidationError("Un Administrador debe estar asociado a una tienda.")
                Administrador.objects.create(user=user, tienda=tienda, **(validated_data.pop('admin_profile', None) or {}))
            elif rol.nombre == 'cliente':
                Cliente.objects.create(user=user, **(validated_data.pop('cliente_profile', None) or {}))
                if tienda: tienda.clientes.add(user)
        return user

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        rol_nombre = instance.rol.nombre if instance.rol else None
        
        tienda_data = None
        if rol_nombre == 'admin' and hasattr(instance, 'admin_profile'):
            tienda = instance.admin_profile.tienda
            tienda_data = {'id': tienda.id, 'nombre': tienda.nombre}
        elif rol_nombre == 'vendedor' and hasattr(instance, 'vendedor_profile'):
            tienda = instance.vendedor_profile.tienda
            tienda_data = {'id': tienda.id, 'nombre': tienda.nombre}
        
        representation['tienda'] = tienda_data
        # Limpiamos los campos write_only de la respuesta
        representation.pop('vendedor_profile', None)
        representation.pop('admin_profile', None)
        representation.pop('cliente_profile', None)
        return representation

# --- Serializers de Detalle (para vistas de lista/detalle) ---
class TiendaBasicSerializer(serializers.ModelSerializer):
    class Meta: model = Tienda; fields = ['id', 'nombre']

class UserBasicSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    class Meta: model = User; fields = ['id_usuario', 'email', 'profile']

class ClienteDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    class Meta: model = Cliente; fields = '__all__'

class VendedorDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    tienda = TiendaBasicSerializer(read_only=True)
    class Meta: model = Vendedor; fields = '__all__'

class AdministradorDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    tienda = TiendaBasicSerializer(read_only=True)
    class Meta: model = Administrador; fields = '__all__'

# --- SERIALIZERS PARA EDITAR PERFIL ---
# --- SERIALIZADOR 1: Solo los campos del perfil anidado ---
class ProfileDataSerializer(serializers.ModelSerializer):
    """
    Serializador anidado que SOLO contiene los campos que el usuario
    puede editar de su UserProfile.
    """
    class Meta:
        model = UserProfile
        fields = (
            'ci', 
            'nombre', 
            'apellido', 
            'direccion', 
            'fecha_nacimiento', 
            'telefono', 
            'genero'
        )

# --- SERIALIZADOR 2: Para actualizar el perfil (email + datos) ---
class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializador principal para la acción "me" (PATCH).
    Permite actualizar 'email' y los datos anidados de 'profile'.
    OMITE 'rol' y otros campos sensibles.
    """
    profile = ProfileDataSerializer()

    class Meta:
        model = User
        fields = ('email', 'profile')

    def update(self, instance, validated_data):
        # 1. Actualizar datos del UserProfile anidado
        profile_data = validated_data.pop('profile', None)
        
        if profile_data and hasattr(instance, 'profile'):
            profile_instance = instance.profile
            for attr, value in profile_data.items():
                setattr(profile_instance, attr, value)
            profile_instance.save()

        # 2. Actualizar 'email' del User (si se proporcionó)
        instance.email = validated_data.get('email', instance.email)
        instance.save()

        return instance

# --- SERIALIZADOR 3: Para cambiar la contraseña del propio usuario ---
class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializador para el cambio de contraseña del propio usuario.
    Valida la contraseña antigua antes de permitir el cambio.
    """
    old_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    def validate_old_password(self, value):
        """
        Valida que la contraseña antigua (old_password) sea correcta.
        """
        # Obtenemos el usuario del contexto (que pasaremos desde la vista)
        user = self.context['request'].user
        
        if not user.check_password(value):
            raise serializers.ValidationError("Tu contraseña antigua no es correcta.")
        
        return value

    def validate_new_password(self, value):
        """
        (Opcional) Puedes agregar validaciones de fortaleza de contraseña aquí.
        Por ejemplo, que tenga al menos 8 caracteres.
        """
        if len(value) < 8:
            raise serializers.ValidationError("La nueva contraseña debe tener al menos 8 caracteres.")
        return value
    
# -- SERIALIZADOR 4: EDITAR FOTO DE PERFIL --
class UserPhotoSerializer(serializers.ModelSerializer):
    """
    Serializador dedicado EXCLUSIVAMENTE a subir/actualizar
    la foto_perfil del UserProfile.
    
    Gracias a 'django-cloudinary-storage', cuando 'save()' se llame,
    esto subirá el archivo directamente a Cloudinary.
    """
    class Meta:
        model = UserProfile
        fields = ('foto_perfil',)