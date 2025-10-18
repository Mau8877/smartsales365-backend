from django.conf import settings
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from apps.saas.models import Tienda

# --- MODELO DE ROL ---
class Rol(models.Model):
    OPCIONES_ESTADO = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
    ]
    OPCIONES_NOMBRE = [
        ('superAdmin', 'Super Administrador'),
        ('admin', 'Administrador'),
        ('cliente', 'Cliente'),
        ('vendedor', 'Vendedor'),
    ]
    nombre = models.CharField(max_length=50, choices=OPCIONES_NOMBRE, unique=True)
    estado = models.CharField(max_length=10, choices=OPCIONES_ESTADO, default='ACTIVO')
    descripcion = models.TextField()

    def __str__(self):
        return self.get_nombre_display()
    
    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

# --- GESTOR DE USUARIOS PERSONALIZADO ---
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es un campo obligatorio.')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # Usamos el método set_password del propio modelo User
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser debe tener is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser debe tener is_superuser=True.')

        # El superuser no pertenece a ninguna tienda
        extra_fields.setdefault('tienda', None)
        
        # Asignamos el rol de superAdmin si no se especifica
        if 'rol' not in extra_fields:
            rol, created = Rol.objects.get_or_create(
                nombre='superAdmin', 
                defaults={'descripcion': 'Acceso total al sistema y a todas las tiendas.'}
            )
            extra_fields['rol'] = rol
            
        return self.create_user(email, password, **extra_fields)

# --- MODELO DE USUARIO PRINCIPAL ---
class User(AbstractBaseUser, PermissionsMixin):
    id_usuario = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.PROTECT,
        related_name='usuarios',
        null=True,
        blank=True,
        verbose_name="Tienda (Tenant)"
    )

    is_active = models.BooleanField(default=True, verbose_name="Activo")
    is_staff = models.BooleanField(default=False, verbose_name="Es Staff (acceso al admin)")
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, null=True, blank=True)

    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        # Lógica para asegurar la coherencia de la tienda y el rol
        if self.rol and self.rol.nombre in ['admin', 'vendedor'] and not self.tienda:
            raise ValueError(f"Un usuario con rol '{self.rol.nombre}' debe estar asociado a una tienda.")
        if self.rol and self.rol.nombre in ['superAdmin', 'cliente'] and self.tienda:
            self.tienda = None
        super().save(*args, **kwargs)

    # --- MÉTODOS PERSONALIZADOS  ---
    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_staff

    def puede_acceder_sistema(self):
        """Verifica si el usuario puede acceder al sistema basado en su rol y estado."""
        if not self.is_active:
            return False
        if not self.rol:
            return False
        if self.rol.nombre == 'superAdmin':
            return True
        return self.rol.estado == 'ACTIVO'

    def __str__(self):
        rol_nombre = self.rol.get_nombre_display() if self.rol else "Sin Rol"
        tienda_nombre = f" [Tienda: {self.tienda.nombre}]" if self.tienda else " [Global]"
        return f"{self.email} ({rol_nombre}){tienda_nombre}"
    
    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
    
# --- PERFILES DE USUARIO ---
class UserProfile(models.Model):
    OPCIONES_GENERO = [
        ('MASCULINO', 'Masculino'),
        ('FEMENINO', 'Femenino'),
        ('OTRO', 'Otro'),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile', primary_key=True)
    ci = models.CharField(max_length=20, unique=True, blank=True, null=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    direccion = models.TextField(blank=True, null=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    foto_perfil = models.ImageField(upload_to='fotos_perfil/', null=True, blank=True)
    genero = models.CharField(max_length=20, choices=OPCIONES_GENERO, null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

class Cliente(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cliente_profile', primary_key=True)
    nivel_fidelidad = models.CharField(max_length=50, default='Bronce')
    puntos_acumulados = models.IntegerField(default=0)

    def __str__(self):
        return f"Cliente: {self.user.email}"
    
class Vendedor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vendedor_profile', primary_key=True)
    fecha_contratacion = models.DateField(null=True, blank=True)
    ventas_realizadas = models.IntegerField(default=0)
    tasa_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Vendedor: {self.user.email}"
    
class Administrador(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_profile', primary_key=True)
    departamento = models.CharField(max_length=100, null=True, blank=True)
    fecha_contratacion = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Administrador: {self.user.email}"