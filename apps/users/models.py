from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

# MODELO DE ROL
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
        return self.nombre

# MODELO DE CUSTOM MANAGER
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El usuario debe tener una dirección de email válida.')
            
        # Normaliza el email (todo en minúsculas)
        email = self.normalize_email(email)
        
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)
    
# MODELO DE USUARIO PERSONALIZADO
class User(AbstractBaseUser):
    # Campos del modelo de usuario
    id_usuario = models.BigAutoField(primary_key=True)
    password = models.CharField(max_length=128)
    email = models.EmailField(unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Campos requeridos por AbstractBaseUser Django
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    objects = UserManager()
    
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE, null=True)

    # Campo que se usará para el login (Email)
    USERNAME_FIELD = 'email'     

    # Campos que se piden al crear un superusuario
    REQUIRED_FIELDS = []         

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        self.save()
    
    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    def has_perm(self, perm, obj=None):
        # Simplificación: permite que el superusuario acceda a todo
        return self.is_superuser

    def has_module_perms(self, app_label):
        # Simplificación: permite que el is_staff acceda a los módulos del Admin
        return self.is_staff

    def puede_acceder_sistema(self):
        """Verifica si el usuario puede acceder al sistema"""
        # Super admin siempre puede acceder
        if self.rol and self.rol.nombre == 'superAdmin':
            return True
        
        # Usuarios normales solo si su rol esta activo
        if self.rol:
            return self.rol.estado in ['ACTIVO']
        
        return False

    def __str__(self):
        return f"{self.email} ({self.rol.nombre if self.rol else 'Sin Rol'})"

# Modelo UserProfile para información adicional del usuario
class UserProfile(models.Model):
    OPCIONES_GENERO = [
        ('MASCULINO', 'Masculino'),
        ('FEMENINO', 'Femenino'),
        ('OTRO', 'Otro'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    ci = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    direccion = models.TextField(blank=True, null=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    genero = models.CharField(max_length=10, null=True, blank=True)
    foto_perfil = models.ImageField(upload_to='fotos_perfil/', null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.user.email})"

class Cliente(models.Model):
    OPCIONES_NIVEL_FIDELIDAD = [
        ('BRONCE', 'Bronce'),
        ('PLATA', 'Plata'),
        ('ORO', 'Oro'),
        ('PLATINO', 'Platino'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cliente_profile')
    nivel_fidelidad = models.CharField(max_length=50, null=True, blank=True)
    puntos_acumulados = models.IntegerField(default=0)

    def __str__(self):
        return f"Cliente: {self.user.email} - Nivel: {self.nivel_fidelidad}"
    
class Vendedor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendedor_profile')
    fecha_contratacion = models.DateField(null=True, blank=True)
    ventas_realizadas = models.IntegerField(default=0)
    tasa_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Vendedor: {self.user.email} - Ventas: {self.ventas_realizadas}"
    
class Administrador(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile')
    departamento = models.CharField(max_length=100, null=True, blank=True)
    fecha_contratacion = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Administrador: {self.user.email} - Departamento: {self.departamento}"