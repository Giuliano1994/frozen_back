import django_filters
from .models import OrdenVenta

class OrdenVentaFilter(django_filters.FilterSet):
    fecha_desde = django_filters.DateTimeFilter(field_name="fecha", lookup_expr="gte")
    fecha_hasta = django_filters.DateTimeFilter(field_name="fecha", lookup_expr="lte")
    cliente = django_filters.CharFilter(field_name="id_cliente__nombre", lookup_expr="icontains")
    estado = django_filters.NumberFilter(field_name="id_estado_venta__id_estado_venta")
    prioridad = django_filters.NumberFilter(field_name="id_prioridad__id_prioridad")

    class Meta:
        model = OrdenVenta
        fields = [
            "fecha_desde",
            "fecha_hasta",
            "cliente",
            "estado",
            "prioridad",
        ]