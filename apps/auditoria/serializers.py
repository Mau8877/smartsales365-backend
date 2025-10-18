from rest_framework import serializers
from .models import Bitacora
from apps.users.models import User
from apps.users.serializers import UserProfileSerializer, RolSerializer 

# Serializer simplificado para mostrar la información del usuario en la bitácora
class BitacoraUserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    rol = RolSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id_usuario', 'email', 'profile', 'rol']

# Serializer Principal de Bitácora
class BitacoraSerializer(serializers.ModelSerializer):
    # Anidamos la información completa del usuario que realizó la acción
    user = BitacoraUserSerializer(read_only=True)
    # Campo para truncar la acción en caso de ser muy larga
    accion_corta = serializers.CharField(source='accion', read_only=True)

    class Meta:
        model = Bitacora
        fields = '__all__'
        read_only_fields = ('__all__',)