from django.db import models
from apps.users.models import User

# Modelo para registrar las acciones de auditoría en el sistema
class Bitacora(models.Model):  
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bitacoras'
    )
    
    accion = models.TextField(
        help_text="Descripción legible de la acción"
    )
    
    ip = models.GenericIPAddressField(null=True, blank=True)
    
    objeto = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Texto corto indicando el objeto afectado"
    )
    
    extra = models.JSONField(
        null=True,
        blank=True,
        help_text="Información adicional en JSON (opcional)"
    )
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Registro de bitácora'
        verbose_name_plural = 'Bitácoras'

    def __str__(self):
        if self.user:
            try:
                user_info = f"{self.user.profile.nombre} ({self.user.email})"
            except:
                user_info = self.user.email 
        else:
            user_info = "Anónimo"
        rol_info = f" ({self.user.rol.nombre})" if self.user and self.user.rol else ""
        return f"{self.timestamp.isoformat()} — {user_info}{rol_info} — {self.accion[:80]}..."