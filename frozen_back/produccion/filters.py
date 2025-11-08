import django_filters
from .models import EstadoOrdenProduccion, OrdenDeTrabajo, OrdenProduccion


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
    producto = django_filters.NumberFilter(
        field_name='id_producto__id_producto', label='ID de Producto'
    )

    class Meta:
        model = OrdenProduccion
        fields = [
            'estado',
            'linea',
            'supervisor',
            'operario',
            'producto',
            'fecha_desde',
            'fecha_hasta',
        ]

    def filter_queryset(self, queryset):
        # Aplicar los filtros normales
        queryset = super().filter_queryset(queryset)

        # Si el filtro 'estado' fue enviado
        estado_id = self.data.get('estado')
        if estado_id:
            try:
                estado = EstadoOrdenProduccion.objects.get(pk=estado_id)
                if estado.descripcion.lower() == 'en proceso':
                    # Ordenar por hora_inicio_produccion (ascendente)
                    queryset = queryset.order_by('-fecha_inicio')
            except EstadoOrdenProduccion.DoesNotExist:
                pass

        return queryset
    
class OrdenDeTrabajoFilter(django_filters.FilterSet):
    # Ejemplo de filtro de rango de fecha más robusto
    fecha_inicio_desde = django_filters.DateFilter(
        field_name='hora_inicio_programada', 
        lookup_expr='gte'
    )
    fecha_inicio_hasta = django_filters.DateFilter(
        field_name='hora_inicio_programada', 
        lookup_expr='lte'
    )

    class Meta:
        model = OrdenDeTrabajo
        fields = [
            'id_linea_produccion',
            'id_estado_orden_trabajo',
            'id_orden_produccion',
            'fecha_inicio_desde',
            'fecha_inicio_hasta',
        ]