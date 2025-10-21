import time
import stripe
import traceback
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from apps.auditoria.utils import log_action
from django.contrib.auth import login

from .models import PlanSuscripcion, Tienda, PagoSuscripcion
from apps.users.models import Administrador, User, UserProfile, Rol
from .serializers import (
    PlanSuscripcionSerializer, TiendaSerializer, PagoSuscripcionSerializer,
    TiendaDetailSerializer, RegistroSerializer
)
from config.pagination import CustomPageNumberPagination
from apps.users.views import IsSuperAdmin

stripe.api_key = settings.STRIPE_SECRET_KEY

# --- ViewSets ---
class PlanSuscripcionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = PlanSuscripcion.objects.all().order_by('precio_mensual')
    serializer_class = PlanSuscripcionSerializer
    permission_classes = [permissions.AllowAny]

class TiendaViewSet(viewsets.ModelViewSet):
    queryset = Tienda.objects.all().select_related('plan', 'admin_contacto', 'admin_contacto__profile')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nombre', 'plan__nombre', 'admin_contacto__email']
    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']: return TiendaDetailSerializer
        return TiendaSerializer
    def get_permissions(self):
        if self.action not in ['list', 'retrieve']: self.permission_classes = [IsSuperAdmin]
        return super().get_permissions()
    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated: return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return self.queryset
        if user.tienda: return self.queryset.filter(id=user.tienda.id)
        return self.queryset.none()

class PagoSuscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PagoSuscripcion.objects.all()
    serializer_class = PagoSuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated: return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return self.queryset
        if user.tienda: return self.queryset.filter(tienda=user.tienda)
        return self.queryset.none()

# --- Lógica de Registro ---

@permission_classes([permissions.AllowAny])
def _iniciar_sesion_y_crear_respuesta(request, user, log_message_prefix):
    """
    Función centralizada que maneja el inicio de sesión, la creación de token,
    el log y la construcción de la respuesta JSON completa.
    """
    login(request, user)  # Esto actualiza el campo last_login de Django
    token, _ = Token.objects.get_or_create(user=user)
    
    tienda_info = f" en Tienda: {user.tienda.nombre}" if user.tienda else ""
    log_message = f"{log_message_prefix}{tienda_info}"
    log_action(request, log_message, f"Usuario: {user.email}", user)

    # Construimos la respuesta JSON estandarizada y completa
    response_data = {
        'status': 'success',
        'token': token.key,
        'user_id': user.id_usuario,
        'rol': user.rol.nombre if user.rol else None,
        'tienda_id': user.tienda.id if user.tienda else None,
        'nombre_completo': f"{user.profile.nombre} {user.profile.apellido}" if hasattr(user, 'profile') else 'N/A'
    }
    return response_data

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def registro_directo_prueba(request):
    serializer = RegistroSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if User.objects.filter(email=data['admin_email']).exists():
        return Response({"error": "Este correo electrónico ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            plan = PlanSuscripcion.objects.get(pk=data['plan_id'])
            if not plan.dias_prueba > 0:
                return Response({"error": "Este endpoint es solo para planes de prueba."}, status=status.HTTP_400_BAD_REQUEST)
            rol_admin, _ = Rol.objects.get_or_create(nombre='admin', defaults={'descripcion': 'Administrador de una tienda.'})
            admin_user = User.objects.create_user(email=data['admin_email'], password=data['admin_password'])
            UserProfile.objects.create(user=admin_user, nombre=data['admin_nombre'], apellido=data['admin_apellido'], ci=data['admin_ci'], telefono=data.get('admin_telefono', ''))
            Administrador.objects.create(user=admin_user, fecha_contratacion=timezone.now().date())
            nueva_tienda = Tienda.objects.create(plan=plan, nombre=data['tienda_nombre'], admin_contacto=admin_user)
            admin_user.tienda = nueva_tienda
            admin_user.rol = rol_admin
            admin_user.save()
            return Response({"message": "¡Tienda de prueba creada exitosamente!", "tienda_id": nueva_tienda.id, "user_id": admin_user.id_usuario}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": f"Ocurrió un error inesperado: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Flujo de Pago con Stripe (Sin Webhooks) ---

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def crear_sesion_pago_stripe(request):
    serializer = RegistroSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if User.objects.filter(email=data['admin_email']).exists():
        return Response({"error": "Este correo electrónico ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        plan = PlanSuscripcion.objects.get(pk=data['plan_id'])
        if not plan.stripe_price_id:
            return Response({"error": f"El plan '{plan.nombre}' no tiene un Price ID de Stripe configurado."}, status=500)
        price_id = plan.stripe_price_id
        base_url = settings.FRONTEND_URL.rstrip('/')
        return_url = f"{base_url}/saas-register/return?session_id={{CHECKOUT_SESSION_ID}}"
        session = stripe.checkout.Session.create(
            ui_mode='embedded', customer_email=data['admin_email'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription', return_url=return_url,
            metadata={
                'plan_id': str(plan.id), 'tienda_nombre': data['tienda_nombre'],
                'admin_nombre': data['admin_nombre'], 'admin_apellido': data['admin_apellido'],
                'admin_ci': data['admin_ci'], 'admin_email': data['admin_email'],
                'admin_password': data['admin_password'], 'admin_telefono': data.get('admin_telefono', '')
            }
        )
        return Response({'clientSecret': session.client_secret})
    except Exception as e:
        return Response({"error": f"Error del servidor al crear sesión: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def confirmar_registro_pago(request):
    session_id = request.data.get('session_id')
    if not session_id:
        return Response({"error": "Falta el ID de la sesión."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != 'paid':
            time.sleep(3)
            session = stripe.checkout.Session.retrieve(session_id)
        if not (session.payment_status == 'paid' and session.invoice):
            return Response({"error": "El pago no se pudo confirmar en Stripe."}, status=status.HTTP_400_BAD_REQUEST)
        
        invoice_id = session.invoice
        with transaction.atomic():
            metadata = session.metadata
            rol_admin, _ = Rol.objects.get_or_create(nombre='admin', defaults={'descripcion': 'Administrador de una tienda.'})
            
            admin_user, created = User.objects.get_or_create(
                email=metadata['admin_email'],
                defaults={'password': make_password(metadata['admin_password'])}
            )

            if not created:
                # ===============================================================
                # CORRECCIÓN: Si el usuario ya existía, llamamos a la función auxiliar
                # para obtener la respuesta COMPLETA.
                # ===============================================================
                response_data = _iniciar_sesion_y_crear_respuesta(request, admin_user, "Inicio de sesión post-registro (usuario ya existía)")
                response_data['message'] = 'El usuario ya fue registrado en una petición anterior.'
                return Response(response_data)
            
            # Si es nuevo, creamos todo...
            plan = PlanSuscripcion.objects.get(pk=metadata['plan_id'])
            UserProfile.objects.create(user=admin_user, nombre=metadata['admin_nombre'], apellido=metadata['admin_apellido'], ci=metadata['admin_ci'], telefono=metadata.get('admin_telefono', ''))
            Administrador.objects.create(user=admin_user, fecha_contratacion=timezone.now().date())
            nueva_tienda = Tienda.objects.create(plan=plan, nombre=metadata['tienda_nombre'], admin_contacto=admin_user)
            
            admin_user.tienda = nueva_tienda
            admin_user.rol = rol_admin
            admin_user.save()

            PagoSuscripcion.objects.create(
                tienda=nueva_tienda, plan_pagado=plan,
                stripe_payment_intent_id=invoice_id,
                monto_total=plan.precio_mensual,
                estado='PAGADO', fecha_pago=timezone.now()
            )
            
            # ===============================================================
            # CORRECCIÓN: Al final, también llamamos a la función auxiliar
            # para obtener la respuesta COMPLETA y consistente.
            # ===============================================================
            response_data = _iniciar_sesion_y_crear_respuesta(request, admin_user, "Registro y primer inicio de sesión vía Stripe")
            return Response(response_data)

    except Exception as e:
        return Response({"error": f"Error final al crear la cuenta: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)