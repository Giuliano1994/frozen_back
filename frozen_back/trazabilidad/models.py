from django.db import models

# Create your models here.


class Configuracion(models.Model):
    """
    Modelo para almacenar variables de configuración del sistema
    de manera parametrizable en la base de datos.
    """
    nombre_clave = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nombre de la Variable (Clave)",
        help_text="Clave única para identificar la variable (e.g., HORAS_LABORABLES_POR_DIA)"
    )
    valor = models.CharField(
        max_length=255,
        verbose_name="Valor"
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
        help_text="Para qué se usa esta variable."
    )
    tipo_dato = models.CharField(
        max_length=20,
        default='int', # o 'str', 'float', 'bool', 'date', etc.
        verbose_name="Tipo de Dato Esperado",
        help_text="Ayuda a convertir el 'valor' al tipo correcto en Python."
    )

    class Meta:
        verbose_name = "Configuración"
        verbose_name_plural = "Configuraciones"

    def __str__(self):
        return f"{self.nombre_clave}: {self.valor} ({self.tipo_dato})"