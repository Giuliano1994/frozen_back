import django_filters
from .models import OrdenDespacho

class OrdenDespachoFilter(django_filters.FilterSet):
    # Filtros por rango de fechas (usa fecha_despacho)
    fecha_desde = django_filters.DateTimeFilter(field_name="fecha_despacho", lookup_expr="gte")
    fecha_hasta = django_filters.DateTimeFilter(field_name="fecha_despacho", lookup_expr="lte")

    # Filtros por nombre del repartidor o por ID del estado
    repartidor = django_filters.CharFilter(field_name="id_repartidor__nombre", lookup_expr="icontains")
    estado = django_filters.NumberFilter(field_name="id_estado_despacho__id_estado_despacho")

    class Meta:
        model = OrdenDespacho
        fields = ["fecha_desde", "fecha_hasta", "repartidor", "estado"]

