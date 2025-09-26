import json
from django.db import models


class Departamento(models.Model):
    id_departamento = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'departamento'
        managed = False


class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'rol'
        managed = False


class Turno(models.Model):
    id_turno = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'turno'
        managed = False


class JSONListField(models.JSONField):
    """Campo personalizado que siempre devuelve listas"""
    
    def from_db_value(self, value, expression, connection):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                return [value]
        return [value]
    

class FaceID(models.Model):
    id_face = models.AutoField(primary_key=True)
    vector = JSONListField()  # Usa el campo personalizado

    class Meta:
        db_table = 'faceid'
        managed = False


class Empleado(models.Model):
    id_empleado = models.AutoField(primary_key=True)
    usuario = models.CharField(max_length=50, unique=True)
    contrasena = models.CharField(max_length=100)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    id_face = models.ForeignKey(FaceID, null=True, on_delete=models.SET_NULL, db_column='id_face')
    id_rol = models.ForeignKey(Rol, on_delete=models.PROTECT, db_column='id_rol')
    id_departamento = models.ForeignKey(Departamento, on_delete=models.PROTECT, db_column='id_departamento')
    id_turno = models.ForeignKey(Turno, on_delete=models.PROTECT, db_column='id_turno')

    class Meta:
        db_table = 'empleado'
        managed = False


class Fichada(models.Model):
    id_fichada = models.AutoField(primary_key=True)
    fecha = models.DateField()
    hora_entrada = models.TimeField(null=True, blank=True)
    hora_salida = models.TimeField(null=True, blank=True)
    id_empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, db_column='id_empleado')

    class Meta:
        db_table = 'fichada'
        managed = False





  