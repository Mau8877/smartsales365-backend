from django.shortcuts import render
import stripe
import json
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

from rest_framework import viewsets, status, permissions, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

# Modelos de esta app (ventas)
from .models import Venta, Detalle_Venta, Pago, Envio

# Modelos de otras apps (users, comercial, saas)
from apps.users.models import Cliente
from apps.comercial.models import Producto, Carrito, Detalle_Carrito
from apps.saas.models import Tienda, TiendaCliente

# --- Configuración de Stripe ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# --- Lógica de Envío ---
def calcular_costo_envio(subtotal):
    """
    Calcula el costo de envío basado en el subtotal.
    Debe ser idéntico a la lógica del frontend.
    """
    if subtotal == 0:
        porcentaje_envio = 0
    elif subtotal < 100:   # Menos de 100 bs
        porcentaje_envio = 15
    elif subtotal < 500:   # Entre 100 y 499.99 bs
        porcentaje_envio = 10
    elif subtotal < 1000:  # Entre 500 y 999.99 bs
        porcentaje_envio = 5
    else:                  # 1000 bs o más
        porcentaje_envio = 0
    
    costo_envio = (subtotal * (Decimal(str(porcentaje_envio)) / Decimal('100.0')))
    return costo_envio.quantize(Decimal('0.01'))


# --- ViewSet para Pagos con Stripe ---

class PagoViewSet(viewsets.GenericViewSet):
    """
    ViewSet para manejar la creación y verificación
    de sesiones de pago con Stripe.
    """
    # Este permiso se aplica a todo el ViewSet por defecto
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='crear-sesion-checkout', 
            permission_classes=[permissions.IsAuthenticated])
    def crear_sesion_checkout(self, request):
        """
        Recibe los items del carrito y una dirección, recalcula el total 
        y crea una sesión de pago de Stripe Checkout.
        """
        
        try:
            cliente = request.user.cliente_profile
        except Cliente.DoesNotExist:
            return Response(
                {"error": "Tu cuenta de usuario no es un cliente válido."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        tienda_id = request.data.get('tienda_id')
        items_data = request.data.get('items', [])
        direccion_entrega = request.data.get('direccion_entrega')
        
        if not tienda_id or not items_data:
            return Response(
                {"error": "Se requiere tienda_id y al menos un item."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not direccion_entrega:
                 return Response(
                {"error": "Se requiere una 'direccion_entrega' para el envío."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            tienda = Tienda.objects.get(pk=tienda_id)
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        
        line_items_for_stripe = []
        try:
            subtotal = Decimal('0.00')
            for item_data in items_data:
                producto = Producto.objects.get(
                    pk=item_data.get('producto_id'), 
                    tienda=tienda, 
                    estado=True
                )
                cantidad = int(item_data.get('cantidad'))
                
                if producto.stock < cantidad:
                    raise serializers.ValidationError(f"Stock insuficiente para {producto.nombre}")
                
                subtotal += (producto.precio * cantidad)

                line_items_for_stripe.append({
                    'price_data': {
                        'currency': 'bob',
                        'product_data': {
                            'name': producto.nombre,
                        },
                        'unit_amount': int(producto.precio * 100),
                    },
                    'quantity': cantidad,
                })

            
            costo_envio = calcular_costo_envio(subtotal)
            total_final = subtotal + costo_envio

        except Producto.DoesNotExist as e:
            return Response({"error": f"Producto no encontrado: {str(e)}"}, status=status.HTTP_404_NOT_FOUND)
        except serializers.ValidationError as e:
            return Response({"error": e.detail[0]}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Error al calcular el total: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
        try:
            metadata = {
                'user_id': request.user.id_usuario,
                'tienda_id': tienda.id,
                'direccion_entrega': direccion_entrega,
                'items_data': json.dumps(items_data)
            }

            if costo_envio > 0:
                line_items_for_stripe.append({
                    'price_data': {
                        'currency': 'bob',
                        'product_data': {
                            'name': 'Costo de Envío',
                        },
                        'unit_amount': int(costo_envio * 100),
                    },
                    'quantity': 1,
                })


            sesion_checkout = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items_for_stripe,
                mode='payment',
                metadata=metadata,
                customer_email=request.user.email,
                
                success_url=f"{settings.FRONTEND_URL}/tienda/{tienda.slug}/pago-exitoso?session_id={{CHECKOUT_SESSION_ID}}",
                
                cancel_url=f"{settings.FRONTEND_URL}/tienda/{tienda.slug}/pagar",
            )
            
            return Response({'url': sesion_checkout.url}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"Error al crear sesión de Stripe: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @action(detail=False, methods=['post'], url_path='verificar-sesion', 
            permission_classes=[permissions.IsAuthenticated]) # <-- CORREGIDO (con corchetes)
    def verificar_sesion_checkout(self, request):
        """
        Verifica una sesión de pago de Stripe después de la redirección
        y crea todos los objetos de la venta (Venta, Pago, Envio, etc.)
        """
        session_id = request.data.get('session_id')
        
        if not session_id:
            return Response({"error": "No se proporcionó session_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.status != 'complete':
                 return Response({"error": "La sesión de pago no está completada."}, status=status.HTTP_400_BAD_REQUEST)
            
            metadata = session.get('metadata', {})
            user_id = metadata.get('user_id')
            tienda_id = metadata.get('tienda_id')
            direccion_entrega = metadata.get('direccion_entrega')
            items_data_str = metadata.get('items_data')
            
            stripe_payment_id = session.get('payment_intent')
            total_pagado_centavos = session.get('amount_total')
            total_pagado = Decimal(total_pagado_centavos) / Decimal(100)

            if not all([user_id, tienda_id, direccion_entrega, items_data_str, stripe_payment_id]):
                print("Verificación de sesión recibió metadata incompleta.")
                return Response({"error": "Metadata incompleta en la sesión."}, status=500)
            
            try:
                items_data = json.loads(items_data_str)
            except json.JSONDecodeError:
                print("Error al decodificar items_data del JSON.")
                return Response(status=400)

            try:
                with transaction.atomic():
                    cliente = Cliente.objects.get(user_id=user_id) 
                    tienda = Tienda.objects.get(pk=tienda_id)
                    
                    asociacion, fue_creado = TiendaCliente.objects.get_or_create(
                        tienda=tienda,
                        cliente_id=user_id
                    )
                    
                    if fue_creado:
                        print(f"Nueva asociación creada: Cliente {user_id} a Tienda {tienda.nombre}")
                    else:
                        print(f"Asociación ya existía: Cliente {user_id} en Tienda {tienda.nombre}")

                    subtotal_seguro = Decimal('0.00')
                    productos_para_actualizar_stock = []
                    
                    detalles_carrito_a_crear = []
                    detalles_venta_a_crear = []

                    nuevo_carrito = Carrito.objects.create(
                        cliente=cliente,
                        tienda=tienda,
                        total=total_pagado
                    )

                    for item in items_data:
                        producto = Producto.objects.select_for_update().get(pk=item.get('producto_id'))
                        cantidad = int(item.get('cantidad'))
                        
                        if producto.stock < cantidad:
                            raise Exception(f"Stock insuficiente para {producto.nombre} durante la verificación.")
                        
                        precio_historico = producto.precio
                        subtotal_seguro += (precio_historico * cantidad)
                        
                        detalles_carrito_a_crear.append(
                            Detalle_Carrito(
                                carrito=nuevo_carrito,
                                producto=producto,
                                cantidad=cantidad,
                                precio_unitario=precio_historico
                            )
                        )
                        
                        producto.stock -= cantidad
                        productos_para_actualizar_stock.append(producto)

                    costo_envio_seguro = calcular_costo_envio(subtotal_seguro)
                    total_final_seguro = subtotal_seguro + costo_envio_seguro
                    
                    if total_final_seguro.quantize(Decimal('0.01')) != total_pagado.quantize(Decimal('0.01')):
                        raise Exception(f"Discrepancia de Total! Stripe cobró {total_pagado} pero el cálculo fue {total_final_seguro}")

                    nueva_venta = Venta.objects.create(
                        total=total_pagado,
                        estado='PROCESADA',
                        tienda=tienda,
                        cliente=cliente,
                        carrito=nuevo_carrito
                    )

                    for item in detalles_carrito_a_crear:
                        detalles_venta_a_crear.append(
                            Detalle_Venta(
                                venta=nueva_venta,
                                producto=item.producto,
                                cantidad=item.cantidad,
                                precio_historico=item.precio_unitario
                            )
                        )
                    
                    Pago.objects.create(
                        venta=nueva_venta,
                        tienda=tienda,
                        stripe_payment_intent_id=stripe_payment_id,
                        monto_total=total_pagado,
                        estado='COMPLETADO'
                    )
                    
                    Envio.objects.create(
                        venta=nueva_venta,
                        tienda=tienda,
                        direccion_entrega=direccion_entrega,
                        estado='EN_PREPARACION'
                    )

                    Detalle_Carrito.objects.bulk_create(detalles_carrito_a_crear)
                    Detalle_Venta.objects.bulk_create(detalles_venta_a_crear)
                    Producto.objects.bulk_update(productos_para_actualizar_stock, ['stock'])
                    
                    puntos_ganados = total_pagado * Decimal('0.0005')
                    cliente.puntos_acumulados += puntos_ganados
                    cliente.save(update_fields=['puntos_acumulados'])

            except Exception as e:
                print(f"Error al procesar la transacción de la sesión: {str(e)}")
                return Response({"error": f"Error al procesar el pedido: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({"success": True, "message": "Pedido creado exitosamente."}, status=status.HTTP_200_OK)

        except stripe.error.StripeError as e:
            return Response({"error": f"Error de Stripe: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": f"Error general: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)