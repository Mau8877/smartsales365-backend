from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta

# Modelo Planes de Suscripción SaaS
class PlanSuscripcion(models.Model):
    PLAN_SUSCRIPCION = [
        ('PRUEBA', 'Prueba'),
        ('BASICO', 'Básico'),
        ('ESTANDAR', 'Estándar'),
        ('PREMIUM', 'Premium'),
    ]
    nombre = models.CharField(max_length=50, unique=True, choices=PLAN_SUSCRIPCION, verbose_name="Nombre del Plan")
    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio Mensual")
    limite_usuarios = models.IntegerField(default=5, verbose_name="Límite de Usuarios (Staff)")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    dias_prueba = models.IntegerField(default=0, help_text="Duración en días para planes de prueba. 0 para planes de pago.")

    def __str__(self):
        if self.nombre == 'PRUEBA':
            return f"Plan de Prueba ({self.dias_prueba} días)"
        return f"{self.get_nombre_display()} (${self.precio_mensual}/mes)"

    class Meta:
        verbose_name = "Plan de Suscripción"
        verbose_name_plural = "Planes de Suscripción"

# Modelo TIENDA (Tenant)
class Tienda(models.Model):
    ESTADOS_SUSCRIPCION = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
        ('CANCELADO', 'Cancelado'),
        ('PRUEBA', 'Prueba'),
    ]
    plan = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.PROTECT,
        related_name='tiendas',
        verbose_name="Plan Contratado"
    )
    nombre = models.CharField(max_length=100, verbose_name="Nombre de la Tienda/Empresa")
    fecha_inicio_servicio = models.DateField(auto_now_add=True, verbose_name="Fecha de Inicio")
    fecha_proximo_cobro = models.DateField(verbose_name="Próximo Cobro", null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_SUSCRIPCION, default='ACTIVO', verbose_name="Estado de Suscripción")
    
    admin_contacto = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tienda_administrada',
        verbose_name="Admin de Contacto"
    )
    
    def save(self, *args, **kwargs):
        if not self.pk and self.plan: # si es un objeto nuevo
            if self.plan.dias_prueba > 0:
                self.fecha_proximo_cobro = timezone.now().date() + relativedelta(days=self.plan.dias_prueba)
                self.estado = 'PRUEBA'
            else:
                self.fecha_proximo_cobro = timezone.now().date() + relativedelta(months=1)
                self.estado = 'ACTIVO'
        super().save(*args, **kwargs)


    def __str__(self):
        return f"Tienda: {self.nombre} - Plan: {self.plan.get_nombre_display()}"

    class Meta:
        verbose_name = "Tienda (Tenant)"
        verbose_name_plural = "Tiendas (Tenants)"
        ordering = ['nombre']

# Modelo Pagos de Suscripción
class PagoSuscripcion(models.Model):
    ESTADOS_PAGO = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('FALLIDO', 'Fallido'),
    ]

    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE,
        related_name='pagos_suscripcion',
        verbose_name="Tienda"
    )
    plan_pagado = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.PROTECT,
        related_name='pagos',
        verbose_name="Plan Pagado"
    )
    stripe_payment_intent_id = models.CharField(max_length=100, unique=True, blank=True, null=True, verbose_name="ID de Payment Intent de Stripe")
    monto_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto Total")
    fecha_emision = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Emisión")
    fecha_pago = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de Pago")
    estado = models.CharField(max_length=20, choices=ESTADOS_PAGO, default='PAGADO', verbose_name="Estado del Pago")
    
    def __str__(self):
        return f"Pago #{self.id} de {self.tienda.nombre} por ${self.monto_total}"

    class Meta:
        verbose_name = "Pago de Suscripción"
        verbose_name_plural = "Pagos de Suscripción"
        ordering = ['-fecha_emision']

