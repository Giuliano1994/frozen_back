import json
from django.db import models


class Departamento(models.Model):
    id_departamento = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'departamento'
        managed = True


class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)
    permisos = models.ManyToManyField('Permiso', through='RolPermiso', related_name='roles')

    class Meta:
        db_table = 'rol'
        managed = True


class Turno(models.Model):
    id_turno = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'turno'
        managed = True


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
        managed = True


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
        managed = True


class Fichada(models.Model):
    id_fichada = models.AutoField(primary_key=True)
    fecha = models.DateField()
    hora_entrada = models.TimeField(null=True, blank=True)
    hora_salida = models.TimeField(null=True, blank=True)
    id_empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, db_column='id_empleado')

    class Meta:
        db_table = 'fichada'
        managed = True



class Permiso(models.Model):
    id_permiso = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField()
    link = models.CharField(max_length=200)

    class Meta:
        db_table = 'permiso'
        managed = True


class RolPermiso(models.Model):
    id_rol_permiso = models.AutoField(primary_key=True)
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE, db_column='id_rol')
    permiso = models.ForeignKey(Permiso, on_delete=models.CASCADE, db_column='id_permiso')

    class Meta:
        db_table = 'rol_permiso'
        managed = True
        unique_together = ('rol', 'permiso')  # evita duplicados



  