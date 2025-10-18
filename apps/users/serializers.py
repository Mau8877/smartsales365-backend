from rest_framework import serializers
from .models import *

# Serializers para los modelos de usuario y perfil
class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['ci', 'nombre', 'apellido', 'direccion', 'fecha_nacimiento', 'telefono', 'genero', 'foto_perfil']

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer()
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)
    puede_acceder = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id_usuario', 'email', 'password', 'rol', 'rol_nombre', 'puede_acceder', 'profile'] 
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def get_puede_acceder(self, obj):
        return obj.puede_acceder_sistema()

    def create(self, validated_data):
        profile_data = validated_data.pop('profile')
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user, **profile_data)
        return user
        
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        profile_data = validated_data.pop('profile', None)
        if profile_data:
            profile = instance.profile
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
        for attr, value in validated_data.items():
            setattr(instance, attr, value) 
        if password:
            instance.set_password(password)
            instance.save()     
        instance.save()
        return instance
    
# Rol Serializer
class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = ['id', 'nombre', 'descripcion', 'estado']

# Cliente Serializer
class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ['id', 'user', 'nivel_fidelidad', 'puntos_acumulados']

# Administrador Serializer
class AdministradorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Administrador
        fields = ['id', 'user', 'departamento', 'fecha_contratacion']

# Vendedor Serializer
class VendedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendedor
        fields = ['id', 'user', 'fecha_contratacion', 'ventas_realizadas', 'tasa_comision']