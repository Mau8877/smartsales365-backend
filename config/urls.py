from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Importaciones para la documentación Swagger 
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

schema_view = get_schema_view(
    openapi.Info(
        title="SmartSales365 API",
        default_version='v1',
        description="Sistema Inteligente de Gestión Comercial y Reportes Dinámicos",
        contact=openapi.Contact(email="maurogurpi@gmail.com"),
        license=openapi.License(name="Private License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


urlpatterns = [
    path('admin/', admin.site.urls),

    # Rutas de documentación (Swagger/Redoc)
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # ----------------------------------------------------------------------
    # API PRINCIPAL (Prefijo /api/v1/)
    # ----------------------------------------------------------------------
    path('api/v1/', include([
        path('usuarios/', include('apps.users.urls')),
        path('auditoria/', include('apps.auditoria.urls')),
        path('comercial/', include('apps.comercial.urls')), 
        path('ventas/', include('apps.ventas.urls')), 
        path('ia/', include('apps.predicciones.urls')), 
        path('reportes/', include('apps.reportes.urls')), 
    ])),
]

# Servir archivos MEDIA y STATIC en entorno de desarrollo (DEBUG=True)
if settings.DEBUG:
    # Permite acceder a las fotos de perfil, etc. (archivos subidos por el usuario)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Permite acceder a los archivos estáticos
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)