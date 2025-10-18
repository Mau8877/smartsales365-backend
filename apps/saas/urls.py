from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PlanSuscripcionViewSet, TiendaViewSet, PagoSuscripcionViewSet

# Creamos un router para registrar las vistas automáticamente
router = DefaultRouter()
router.register(r'planes', PlanSuscripcionViewSet, basename='plan')
router.register(r'tiendas', TiendaViewSet, basename='tienda')
router.register(r'pagos', PagoSuscripcionViewSet, basename='pago')

# Las URLs de la API son generadas automáticamente por el router.
urlpatterns = [
    path('', include(router.urls)),
]
