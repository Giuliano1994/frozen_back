from django.shortcuts import render
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from .serializers import (
    EstadoOrdenProduccionSerializer,
    LineaProduccionSerializer,
    OrdenProduccionSerializer,
    NoConformidadSerializer
)
from .filters import OrdenProduccionFilter


class EstadoOrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = EstadoOrdenProduccion.objects.all()
    serializer_class = EstadoOrdenProduccionSerializer


class LineaProduccionViewSet(viewsets.ModelViewSet):
    queryset = LineaProduccion.objects.all()
    serializer_class = LineaProduccionSerializer


class OrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = OrdenProduccion.objects.all().select_related(
        "id_estado_orden_produccion",
        "id_linea_produccion",
        "id_supervisor",
        "id_operario",
        "id_lote_produccion",
    )
    serializer_class = OrdenProduccionSerializer

    # 🔍 Configuraciones de búsqueda y filtros
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrdenProduccionFilter

    # Campos de búsqueda por texto
    search_fields = [
        'id_estado_orden_produccion__descripcion',
        'id_linea_produccion__descripcion',
        'id_supervisor__nombre',
        'id_operario__nombre',
    ]

    # Campos permitidos para ordenar resultados
    ordering_fields = ['fecha_creacion', 'fecha_inicio', 'cantidad']
    ordering = ['-fecha_creacion']  # orden predeterminado


class NoConformidadViewSet(viewsets.ModelViewSet):
    queryset = NoConformidad.objects.all().select_related("id_orden_produccion")
    serializer_class = NoConformidadSerializer