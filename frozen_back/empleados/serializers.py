from rest_framework import serializers
from .models import (
    Departamento, Turno, FaceID, Rol, Empleado, Fichada,
    Permiso, RolPermiso
)


class DepartamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Departamento
        fields = '__all__'


class TurnoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Turno
        fields = '__all__'


class FaceIDSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaceID
        fields = '__all__'


class PermisoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permiso
        fields = '__all__'


class RolSerializer(serializers.ModelSerializer):
    permisos = PermisoSerializer(many=True, read_only=True)

    class Meta:
        model = Rol
        fields = ['id_rol', 'descripcion', 'permisos']


class RolPermisoSerializer(serializers.ModelSerializer):
    rol = RolSerializer(read_only=True)
    permiso = PermisoSerializer(read_only=True)

    # estos campos aceptan los IDs en POST
    id_rol = serializers.PrimaryKeyRelatedField(
        queryset=Rol.objects.all(), source="rol", write_only=True
    )
    id_permiso = serializers.PrimaryKeyRelatedField(
        queryset=Permiso.objects.all(), source="permiso", write_only=True
    )
    class Meta:
        model = RolPermiso
        fields = '__all__'


class EmpleadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empleado
        fields = '__all__'


class FichadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fichada
        fields = '__all__'
