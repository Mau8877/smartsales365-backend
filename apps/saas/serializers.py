from rest_framework import serializers
from .models import PlanSuscripcion, Tienda, PagoSuscripcion
from apps.users.models import User

# Serializer para el formulario de registro público
class RegistroSerializer(serializers.Serializer):
    """
    Serializer para validar los datos del formulario de registro público.
    No está ligado a un modelo, solo valida la entrada.
    """
    plan_id = serializers.IntegerField()
    tienda_nombre = serializers.CharField(max_length=100)
    admin_nombre = serializers.CharField(max_length=100)
    admin_apellido = serializers.CharField(max_length=100)
    admin_ci = serializers.CharField(max_length=20)
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField(write_only=True, min_length=8)
    admin_telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)


# Serializer para mostrar información básica del admin de contacto
class AdminContactoSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id_usuario', 'email', 'nombre_completo']

    def get_nombre_completo(self, obj):
        return f"{obj.profile.nombre} {obj.profile.apellido}" if hasattr(obj, 'profile') else obj.email

# --- Serializers Principales ---
class PlanSuscripcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanSuscripcion
        fields = '__all__'

class TiendaSerializer(serializers.ModelSerializer):
    """Serializer para crear y actualizar una Tienda."""
    class Meta:
        model = Tienda
        fields = ['id', 'plan', 'nombre', 'fecha_proximo_cobro', 'estado', 'admin_contacto']

class TiendaDetailSerializer(serializers.ModelSerializer):
    """Serializer para ver los detalles de una Tienda."""
    plan = PlanSuscripcionSerializer(read_only=True)
    admin_contacto = AdminContactoSerializer(read_only=True)

    class Meta:
        model = Tienda
        fields = [
            'id', 'plan', 'nombre', 'fecha_inicio_servicio', 
            'fecha_proximo_cobro', 'estado', 'admin_contacto'
        ]

class PagoSuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para ver los pagos de suscripción."""
    plan_pagado = PlanSuscripcionSerializer(read_only=True)
    tienda_nombre = serializers.CharField(source='tienda.nombre', read_only=True)
    
    class Meta:
        model = PagoSuscripcion
        fields = [
            'id', 'tienda', 'tienda_nombre', 'plan_pagado', 'monto_total', 
            'fecha_emision', 'fecha_pago', 'estado', 'stripe_payment_intent_id'
        ]
        read_only_fields = fields
