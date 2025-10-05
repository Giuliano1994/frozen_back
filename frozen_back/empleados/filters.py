import django_filters
from django.db import models
from .models import Empleado


class EmpleadoFilter(django_filters.FilterSet):
    # Filtro por nombre (búsqueda parcial, insensible a mayúsculas)
    nombre = django_filters.CharFilter(
        field_name='nombre', 
        lookup_expr='icontains', 
        label='Nombre'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(f"EmpleadoFilter inicializado con data: {kwargs.get('data', {})}")
    
    # Filtro por apellido (búsqueda parcial, insensible a mayúsculas)
    apellido = django_filters.CharFilter(
        field_name='apellido', 
        lookup_expr='icontains', 
        label='Apellido'
    )
    
    # Filtro por usuario (búsqueda parcial, insensible a mayúsculas)
    usuario = django_filters.CharFilter(
        field_name='usuario', 
        lookup_expr='icontains', 
        label='Usuario'
    )
    
    # Filtro por rol (ID del rol)
    rol = django_filters.NumberFilter(
        field_name='id_rol__id_rol',
        label='ID de Rol'
    )
    
    # Filtro por descripción del rol (búsqueda parcial, insensible a mayúsculas)
    rol_descripcion = django_filters.CharFilter(
        field_name='id_rol__descripcion',
        lookup_expr='icontains',
        label='Descripción del Rol'
    )
    
    # Filtro por departamento (ID del departamento)
    departamento = django_filters.NumberFilter(
        field_name='id_departamento__id_departamento',
        label='ID de Departamento'
    )
    
    # Filtro por descripción del departamento (búsqueda parcial, insensible a mayúsculas)
    departamento_descripcion = django_filters.CharFilter(
        field_name='id_departamento__descripcion',
        lookup_expr='icontains',
        label='Descripción del Departamento'
    )
    
    # Filtro por turno (ID del turno)
    turno = django_filters.NumberFilter(
        field_name='id_turno__id_turno',
        label='ID de Turno'
    )
    
    # Filtro por descripción del turno (búsqueda parcial, insensible a mayúsculas)
    turno_descripcion = django_filters.CharFilter(
        field_name='id_turno__descripcion',
        lookup_expr='icontains',
        label='Descripción del Turno'
    )
    
    # Filtro por nombre completo (busca en nombre Y apellido)
    nombre_completo = django_filters.CharFilter(
        method='filter_nombre_completo',
        label='Nombre Completo'
    )
    
    def filter_nombre_completo(self, queryset, name, value):
        """
        Filtro personalizado que busca en nombre Y apellido simultáneamente
        """
        if not value:
            return queryset
        
        return queryset.filter(
            models.Q(nombre__icontains=value) | 
            models.Q(apellido__icontains=value)
        )

    class Meta:
        model = Empleado
        fields = [
            'nombre',
            'apellido', 
            'usuario',
            'rol',
            'rol_descripcion',
            'departamento',
            'departamento_descripcion',
            'turno',
            'turno_descripcion',
            'nombre_completo',
        ]
