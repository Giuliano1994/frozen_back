from django.utils import timezone
from django.shortcuts import render
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend

from ventas.models import EstadoVenta
from .models import EstadoDespacho, Repartidor, OrdenDespacho, DespachoOrenVenta
from .serializers import (
    CrearOrdenDespachoSerializer,
    EstadoDespachoSerializer,
    RepartidorSerializer,
    OrdenDespachoSerializer,
    DespachoOrdenVentaSerializer,
    HistoricalOrdenDespachoSerializer,
)
from .filters import OrdenDespachoFilter

class estadoDespachoViewSet(viewsets.ModelViewSet):
    queryset = EstadoDespacho.objects.all()
    serializer_class = EstadoDespachoSerializer

class RepartidorViewSet(viewsets.ModelViewSet):
    queryset = Repartidor.objects.all()
    serializer_class = RepartidorSerializer


class despachoOrenVentaViewSet(viewsets.ModelViewSet):
    queryset = DespachoOrenVenta.objects.all()
    serializer_class = DespachoOrdenVentaSerializer


class OrdenDespachoViewSet(viewsets.ViewSet):
    """
    ViewSet personalizado para Órdenes de Despacho.
    Incluye filtros, búsqueda y ordenamiento sin perder list() ni retrieve().
    """

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrdenDespachoFilter
    search_fields = ["id_repartidor__nombre", "id_estado_despacho__descripcion"]
    ordering_fields = ["fecha_despacho"]
    ordering = ["-fecha_despacho"]

    def list(self, request):
        queryset = OrdenDespacho.objects.all()
        # Aplicar filtros, búsqueda y ordenamiento
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(request, queryset, self)
        serializer = OrdenDespachoSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            despacho = OrdenDespacho.objects.get(pk=pk)
        except OrdenDespacho.DoesNotExist:
            return Response({"error": "Orden de despacho no encontrada"}, status=404)
        serializer = OrdenDespachoSerializer(despacho)
        return Response(serializer.data)

    def create(self, request):
        print(request.data)
        serializer = CrearOrdenDespachoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        despacho = serializer.save()
        response_serializer = OrdenDespachoSerializer(despacho)
        return Response(response_serializer.data, status=201)
    
    @action(detail=True, methods=['post'])
    def finalizar(self, request, pk=None):
        """
        Finaliza una orden de despacho.
        Recibe una lista de id_orden_venta entregadas.
        Las entregadas se marcan como 'Despachado',
        las no entregadas como 'Devuelto' y la orden como 'Finalizada'.
        """
        try:
            orden_despacho = OrdenDespacho.objects.get(pk=pk)
        except OrdenDespacho.DoesNotExist:
            return Response({"error": "Orden de despacho no encontrada"}, status=404)

        ordenes_entregadas = request.data.get('ordenes_entregadas', [])

        if not isinstance(ordenes_entregadas, list):
            return Response({"error": "El campo 'ordenes_entregadas' debe ser una lista"}, status=400)

        from django.db import transaction

        with transaction.atomic():
            # Estados necesarios
            estado_despachado, _ = EstadoVenta.objects.get_or_create(descripcion="Despachado")
            estado_pagada, _ = EstadoVenta.objects.get_or_create(descripcion="Pagada")

            estado_despacho_finalizada, _ = EstadoDespacho.objects.get_or_create(descripcion="Finalizada")
            estado_despacho_despachado, _ = EstadoDespacho.objects.get_or_create(descripcion="Despachado")
            estado_despacho_devuelto, _ = EstadoDespacho.objects.get_or_create(descripcion="Devuelto")

            # Obtener todas las relaciones despacho-orden-venta
            relaciones = DespachoOrenVenta.objects.filter(id_orden_despacho=orden_despacho)

            for relacion in relaciones:
                orden_venta = relacion.id_orden_venta

                if orden_venta.id_orden_venta in ordenes_entregadas:
                    # ✅ Entregada
                    orden_venta.id_estado_venta = estado_despachado
                    orden_venta.fecha_entrega = timezone.now()
                    relacion.id_estado_despacho = estado_despacho_despachado
                else:
                    # ❌ No entregada
                    orden_venta.id_estado_venta = estado_pagada
                    relacion.id_estado_despacho = estado_despacho_devuelto

                orden_venta.save()
                relacion.save()

            # Cambiar estado de la orden de despacho
            orden_despacho.id_estado_despacho = estado_despacho_finalizada
            orden_despacho.save()

        return Response({
            "mensaje": "Orden de despacho finalizada correctamente",
            "id_orden_despacho": orden_despacho.id_orden_despacho,
            "ordenes_entregadas": ordenes_entregadas
        }, status=status.HTTP_200_OK)
    





class HistorialOrdenDespachoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para ver el historial de cambios de las Órdenes de Despacho.
    """
    queryset = OrdenDespacho.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalOrdenDespachoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_estado_despacho', 'id_repartidor']
    search_fields = ['history_user__usuario', 'id_repartidor__nombre']