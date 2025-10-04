from django.shortcuts import render
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from stock.models import LoteProduccion, EstadoLoteProduccion
from .serializers import (
    EstadoOrdenProduccionSerializer,
    LineaProduccionSerializer,
    OrdenProduccionSerializer,
    NoConformidadSerializer
)
from .filters import OrdenProduccionFilter
from django.utils import timezone
from datetime import timedelta


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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrdenProduccionFilter
    search_fields = ['id_estado_orden_produccion__descripcion', 'id_linea_produccion__descripcion']
    ordering_fields = ['fecha_creacion', 'cantidad']
    ordering = ['-fecha_creacion']

    def perform_create(self, serializer):
        # Buscar el estado inicial "Pendiente de inicio"
        estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")

        # Guardar la orden con ese estado
        orden = serializer.save(id_estado_orden_produccion=estado_inicial)

        # Buscar el estado "En espera" para el lote
        estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")

        # Crear lote asociado al producto
        lote = LoteProduccion.objects.create(
            id_producto=orden.id_producto,  # requiere que OrdenProduccion tenga este campo
            fecha_produccion=timezone.now().date(),
            fecha_vencimiento=timezone.now().date() + timedelta(days=orden.id_producto.dias_duracion),
            cantidad=orden.cantidad,
            id_estado_lote_produccion=estado_espera
        )

        # Asignar el lote recién creado a la orden
        orden.id_lote_produccion = lote
        orden.save()
 

class NoConformidadViewSet(viewsets.ModelViewSet):
    queryset = NoConformidad.objects.all().select_related("id_orden_produccion")
    serializer_class = NoConformidadSerializer