import django_filters
from .models import OrdenProduccion


class OrdenProduccionFilter(django_filters.FilterSet):
    fecha_desde = django_filters.DateFilter(
        field_name='fecha_creacion', lookup_expr='gte', label='Fecha desde'
    )
    fecha_hasta = django_filters.DateFilter(
        field_name='fecha_creacion', lookup_expr='lte', label='Fecha hasta'
    )
    estado = django_filters.NumberFilter(
        field_name='id_estado_orden_produccion__id_estado_orden_produccion'
    )
    linea = django_filters.NumberFilter(
        field_name='id_linea_produccion__id_linea_produccion'
    )
    supervisor = django_filters.NumberFilter(
        field_name='id_supervisor__id_empleado'
    )
    operario = django_filters.NumberFilter(
        field_name='id_operario__id_empleado'
    )

    class Meta:
        model = OrdenProduccion
        fields = [
            'estado',
            'linea',
            'supervisor',
            'operario',
            'fecha_desde',
            'fecha_hasta',
        ]