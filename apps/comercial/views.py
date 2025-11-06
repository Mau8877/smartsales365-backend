from rest_framework import viewsets, status, permissions, serializers, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F
from .models import (
    Marca, Categoria, LogPrecioProducto, Producto, Foto, 
    Carrito, Detalle_Carrito
)
from .serializers import (
    MarcaSerializer, CategoriaSerializer, LogPrecioProductoSerializer,
    ProductoSerializer, FotoSerializer, CarritoSerializer,
    AddDetalleCarritoSerializer
)
from apps.auditoria.utils import log_action
from config.pagination import CustomPageNumberPagination
from apps.users.utils import get_user_tienda 
from apps.saas.models import Tienda

class IsSuperAdmin(permissions.BasePermission):
    """ Permite el acceso solo a usuarios con el rol de superAdmin. """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol and request.user.rol.nombre == 'superAdmin'

class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Permite acceso de LECTURA (GET) a cualquier usuario autenticado,
    pero solo permite ESCRITURA (POST, PUT, DELETE) a Admins o SuperAdmins.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.rol and request.user.rol.nombre in ['admin', 'superAdmin']

# --- ViewSet Base Multi-Tenancy ---

class TenantAwareViewSet(viewsets.ModelViewSet):
    """
    Un ViewSet base que filtra el queryset para la tienda del usuario actual
    y asigna automáticamente la tienda al crear nuevos objetos.
    El superAdmin puede ver todos los datos.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    def get_queryset(self):
        """ Filtra el queryset por la tienda del usuario. """
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.rol and user.rol.nombre == 'superAdmin':
            return queryset # SuperAdmin ve todo
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(tienda=tienda_actual)
        
        return queryset.none() # No es SuperAdmin y no tiene tienda

    def get_serializer_context(self):
        """ Inyecta la tienda y el request en el serializer. """
        context = super().get_serializer_context()
        context['request'] = self.request
        
        if self.request.user.is_authenticated:
            context['usuario'] = self.request.user
            if not (self.request.user.rol and self.request.user.rol.nombre == 'superAdmin'):
                context['tienda'] = get_user_tienda(self.request.user)
        
        return context

    def perform_create(self, serializer):
        """ Asigna automáticamente la tienda al crear un objeto. """
        user = self.request.user
        
        if user.rol and user.rol.nombre == 'superAdmin':
            # El SuperAdmin debe proveer 'tienda_id' en el request
            # (O podríamos forzarlo a seleccionar una)
            # Por ahora, confiamos en que el serializer lo maneje
            serializer.save() 
        else:
            tienda_actual = get_user_tienda(user)
            if not tienda_actual:
                raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
            
            # Pasa el 'usuario' al serializer para el log de auditoría
            serializer.save(tienda=tienda_actual, usuario=user)
    
    def perform_update(self, serializer):
        # Pasa el 'usuario' al serializer para el log de auditoría
        serializer.save(usuario=self.request.user)


# --- ViewSets de Catálogo ---
class MarcaViewSet(TenantAwareViewSet):
    """ API endpoint para Marcas, filtrado por tienda. """
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'estado']

    # --- ¡LOG DE AUDITORÍA AÑADIDO! ---
    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        # El 'usuario' es ignorado por el serializer de Marca, pero está bien pasarlo
        marca = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó Marca", f"Marca: {marca.nombre} (ID: {marca.id})", user)

    def perform_update(self, serializer):
        # Guardamos el estado original para loguear el cambio
        original_estado = serializer.instance.estado
        
        # El 'usuario' es ignorado por el serializer, lo cual está bien
        marca = serializer.save(usuario=self.request.user)
        
        # Lógica de Log para "Activar" / "Desactivar"
        accion = "Actualizó Marca"
        if 'estado' in serializer.validated_data:
            if original_estado != marca.estado:
                accion = "Activó Marca" if marca.estado else "Desactivó Marca"
                
        log_action(self.request, accion, f"Marca: {marca.nombre} (ID: {marca.id})", self.request.user)

    def perform_destroy(self, instance):
        """
        Implementa el BORRADO LÓGICO.
        En lugar de borrar, cambia el estado a 'False'.
        """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado: # Solo desactiva si estaba activa
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Marca (vía Delete)", f"Marca: {nombre} (ID: {id_instancia})", self.request.user)
        # Si ya estaba inactiva, no hacemos nada o podríamos borrarla
        # (Por seguridad, no hacemos nada)

class CategoriaViewSet(TenantAwareViewSet):
    """ API endpoint para Categorías, filtrado por tienda. """
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    search_fields = ['nombre']
    # --- CORRECCIÓN AQUÍ ---
    ordering_fields = ['nombre', 'estado'] # Añadido 'estado' para ordenar

    # --- ¡LOG DE AUDITORÍA AÑADIDO A CATEGORIA! ---
    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        # El 'usuario' es ignorado por el serializer, pero está bien pasarlo
        categoria = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó Categoría", f"Categoría: {categoria.nombre} (ID: {categoria.id})", user)

    def perform_update(self, serializer):
        # Guardamos el estado original para loguear el cambio
        original_estado = serializer.instance.estado
        
        # El 'usuario' es ignorado por el serializer
        categoria = serializer.save(usuario=self.request.user)
        
        # Lógica de Log para "Activar" / "Desactivar"
        accion = "Actualizó Categoría"
        if 'estado' in serializer.validated_data:
            if original_estado != categoria.estado:
                accion = "Activó Categoría" if categoria.estado else "Desactivó Categoría"
                
        log_action(self.request, accion, f"Categoría: {categoria.nombre} (ID: {categoria.id})", self.request.user)

    def perform_destroy(self, instance):
        """ Implementa el BORRADO LÓGICO. """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado: # Solo desactiva si estaba activa
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Categoría (vía Delete)", f"Categoría: {nombre} (ID: {id_instancia})", self.request.user)



class LogPrecioProductoViewSet(TenantAwareViewSet):
    """ API endpoint de solo lectura para el historial de precios. """
    queryset = LogPrecioProducto.objects.select_related('producto', 'usuario_que_modifico').all()
    serializer_class = LogPrecioProductoSerializer
    http_method_names = ['get', 'head', 'options'] # Solo lectura
    filterset_fields = ['producto']
    ordering_fields = ['-fecha_cambio']

class FotoViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    ViewSet simple para permitir BORRAR fotos.
    El frontend lo usará para gestionar las fotos eliminadas.
    """
    queryset = Foto.objects.all()
    serializer_class = FotoSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly] 

    def get_queryset(self):
        """ El usuario solo puede borrar fotos de su propia tienda """
        user = self.request.user
        if user.rol and user.rol.nombre == 'superAdmin':
            return Foto.objects.all()
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            # Filtra fotos que pertenezcan a productos de la tienda del usuario
            return Foto.objects.filter(producto__tienda=tienda_actual)
        
        return Foto.objects.none()

class ProductoViewSet(TenantAwareViewSet):
    """ API endpoint para Productos. """
    queryset = Producto.objects.select_related('marca', 'tienda').prefetch_related('categorias', 'fotos').all()
    serializer_class = ProductoSerializer
    
    # Filtros
    search_fields = ['nombre', 'descripcion', 'codigo_referencia']
    ordering_fields = ['nombre', 'precio', 'stock', 'estado']
    filterset_fields = {
        'marca': ['exact'],
        'categorias': ['exact'],
        'estado': ['exact'],
        'precio': ['gte', 'lte'],
    }

    # Sobrescribimos perform_create y perform_update para el log de auditoría
    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             # SuperAdmin debe especificar la tienda en el request
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        # Pasamos el 'usuario' para el log y la 'tienda'
        producto = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó producto", f"Producto: {producto.nombre}", user)

    def perform_update(self, serializer):
        # --- CORRECCIÓN AQUÍ (Añadir log de estado) ---
        original_estado = serializer.instance.estado
        
        # El método .save() del serializer ya pasa el usuario
        producto = serializer.save() 
        
        accion = "Actualizó Producto"
        if 'estado' in serializer.validated_data:
            if original_estado != producto.estado:
                accion = "Activó Producto" if producto.estado else "Desactivó Producto"
        
        log_action(self.request, accion, f"Producto: {producto.nombre} (ID: {producto.id})", self.request.user)

    def perform_destroy(self, instance):
        # --- CORRECCIÓN AQUÍ (Borrado lógico) ---
        """ Implementa el BORRADO LÓGICO para Productos. """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado:
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Producto (vía Delete)", f"Producto: {nombre} (ID: {id_instancia})", self.request.user)
        # --- FIN DE LA CORRECCIÓN DE PRODUCTO ---

    @action(
        detail=True, 
        methods=['post'], 
        permission_classes=[IsAuthenticated, IsAdminOrReadOnly],
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload-foto'
    )
    def upload_foto(self, request, pk=None):
        """ Sube o actualiza una foto para un producto. """
        producto = self.get_object()
        
        if 'foto' not in request.FILES:
            return Response({"error": "No se proporcionó ninguna imagen."}, status=status.HTTP_400_BAD_REQUEST)

        data = {'producto': producto.pk, 'foto': request.FILES['foto']}
        
        # Si 'principal' se envía en el form-data, se usa
        if 'principal' in request.data:
            data['principal'] = request.data.get('principal')

        serializer = FotoSerializer(data=data, context=self.get_serializer_context())
        
        if serializer.is_valid():
            # Si es la foto principal, desmarca las otras
            if serializer.validated_data.get('principal', False):
                producto.fotos.update(principal=False)
            
            foto = serializer.save()
            log_action(request, "Subió foto de producto", f"Producto: {producto.nombre}", request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(
        detail=True, 
        methods=['post'], 
        permission_classes=[IsAuthenticated, IsAdminOrReadOnly],
        url_path='set-principal-foto'
    )
    def set_principal_foto(self, request, pk=None):
        """
        Establece una foto EXISTENTE como la principal.
        Espera un JSON: { "foto_id": "ID_DE_LA_FOTO" }
        """
        producto = self.get_object()
        foto_id = request.data.get('foto_id')

        if not foto_id:
            return Response(
                {"error": "'foto_id' es requerido."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Desmarca todas las fotos de este producto
            producto.fotos.update(principal=False)
            
            # Marca la foto seleccionada como principal
            foto = Foto.objects.get(pk=foto_id, producto=producto)
            foto.principal = True
            foto.save()
            
            return Response(
                {"success": f"Foto {foto_id} es ahora la principal."}, 
                status=status.HTTP_200_OK
            )
            
        except Foto.DoesNotExist:
            return Response(
                {"error": "Foto no encontrada o no pertenece a este producto."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# --- ViewSets de Carrito ---

class CarritoViewSet(viewsets.GenericViewSet):
    """
    API endpoint para gestionar el carrito de compras del cliente.
    Se accede principalmente a través de /api/comercial/carritos/mi_carrito/
    """
    queryset = Carrito.objects.prefetch_related(
        'items__producto__fotos' # Optimización profunda
    ).all()
    serializer_class = CarritoSerializer
    permission_classes = [IsAuthenticated]

    def get_carrito_activo(self, request):
        """ Helper para obtener o crear el carrito del cliente. """
        try:
            # Asumimos que la relación inversa de User a Cliente es 'cliente_profile'
            cliente = request.user.cliente_profile
        except Exception:
            raise serializers.ValidationError("Tu usuario no es un cliente válido.")
        
        tienda = get_user_tienda(request.user) # Obtenemos la tienda del cliente/usuario
        if not tienda:
            # Fallback o lógica para clientes de múltiples tiendas
            raise serializers.ValidationError("No se pudo determinar la tienda para este carrito.")

        carrito, created = Carrito.objects.get_or_create(
            cliente=cliente,
            # (Opcional) Podrías añadir un filtro de 'estado=ACTIVO' si lo implementas
            defaults={'tienda': tienda}
        )
        return carrito

    @action(detail=False, methods=['get'], url_path='mi_carrito')
    def mi_carrito(self, request):
        """ Obtiene el carrito activo del usuario actual. """
        carrito = self.get_carrito_activo(request)
        serializer = self.get_serializer(carrito)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='mi_carrito/add')
    def add_item(self, request):
        """ Añade un producto al carrito activo. """
        carrito = self.get_carrito_activo(request)
        serializer = AddDetalleCarritoSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        producto_id = serializer.validated_data['producto_id']
        cantidad_a_anadir = serializer.validated_data['cantidad']
        
        try:
            producto = Producto.objects.get(pk=producto_id, tienda=carrito.tienda)
        except Producto.DoesNotExist:
             return Response({"error": "Producto no encontrado en esta tienda."}, status=status.HTTP_404_NOT_FOUND)

        # Validar stock
        if producto.stock < cantidad_a_anadir:
            return Response({"error": f"Stock insuficiente. Disponible: {producto.stock}"}, status=status.HTTP_400_BAD_REQUEST)

        # Busca el item o créalo
        item, created = Detalle_Carrito.objects.get_or_create(
            carrito=carrito,
            producto=producto,
            defaults={'cantidad': cantidad_a_anadir}
        )

        if not created:
            # Si el item ya existe, suma la cantidad
            nueva_cantidad = item.cantidad + cantidad_a_anadir
            if producto.stock < nueva_cantidad:
                 return Response({"error": f"Stock insuficiente. Tienes {item.cantidad} en el carrito. Disponible: {producto.stock}"}, status=status.HTTP_400_BAD_REQUEST)
            
            item.cantidad = F('cantidad') + cantidad_a_anadir
            item.save()
        
        # log_action(request, "Añadió item al carrito", f"Producto: {producto.nombre} (Cant: {cantidad_a_anadir})", request.user)
        return Response(self.get_serializer(carrito).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['put'], url_path='mi_carrito/items/(?P<detalle_pk>[^/.]+)')
    def update_item(self, request, detalle_pk=None):
        """ Actualiza la cantidad de un item en el carrito. """
        carrito = self.get_carrito_activo(request)
        
        try:
            item = Detalle_Carrito.objects.get(pk=detalle_pk, carrito=carrito)
        except Detalle_Carrito.DoesNotExist:
            return Response({"error": "Item no encontrado en el carrito."}, status=status.HTTP_404_NOT_FOUND)

        cantidad = request.data.get('cantidad')
        if cantidad is None:
            return Response({"error": "'cantidad' es requerida."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            cantidad = int(cantidad)
            if cantidad <= 0:
                # Si la cantidad es 0 o menos, elimina el item
                return self.remove_item(request, detalle_pk)
        except ValueError:
            return Response({"error": "'cantidad' debe ser un número entero."}, status=status.HTTP_400_BAD_REQUEST)

        # Validar stock
        if item.producto.stock < cantidad:
            return Response({"error": f"Stock insuficiente. Disponible: {item.producto.stock}"}, status=status.HTTP_400_BAD_REQUEST)
        
        item.cantidad = cantidad
        item.save()
        
        log_action(request, "Actualizó item en carrito", f"Producto: {item.producto.nombre} (Cant: {cantidad})", request.user)
        return Response(self.get_serializer(carrito).data, status=status.HTTP_200_OK)


    @action(detail=False, methods=['delete'], url_path='mi_carrito/items/(?P<detalle_pk>[^/.]+)')
    def remove_item(self, request, detalle_pk=None):
        """ Elimina un item del carrito. """
        carrito = self.get_carrito_activo(request)
        
        try:
            item = Detalle_Carrito.objects.get(pk=detalle_pk, carrito=carrito)
        except Detalle_Carrito.DoesNotExist:
            return Response({"error": "Item no encontrado en el carrito."}, status=status.HTTP_404_NOT_FOUND)
        
        nombre_producto = item.producto.nombre
        item.delete()
        
        log_action(request, "Eliminó item de carrito", f"Producto: {nombre_producto}", request.user)
        return Response(self.get_serializer(carrito).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['delete'], url_path='mi_carrito/clear')
    def clear_carrito(self, request):
        """ Elimina todos los items del carrito. """
        carrito = self.get_carrito_activo(request)
        carrito.items.all().delete()
        
        log_action(request, "Vació el carrito", "Todos los items eliminados", request.user)
        return Response(self.get_serializer(carrito).data, status=status.HTTP_200_OK)

