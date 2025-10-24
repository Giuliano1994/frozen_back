from django.shortcuts import render
from rest_framework import viewsets, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import OrdenDespacho
from django_filters.rest_framework import DjangoFilterBackend
from .models import EstadoDespacho, Repartidor, OrdenDespacho, DespachoOrenVenta
from .serializers import CrearOrdenDespachoSerializer, EstadoDespachoSerializer, RepartidorSerializer, OrdenDespachoSerializer, DespachoOrdenVentaSerializer, HistoricalOrdenDespachoSerializer

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
    def list(self, request):
        queryset = OrdenDespacho.objects.all()
        serializer = OrdenDespachoSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        despacho = OrdenDespacho.objects.get(pk=pk)
        serializer = OrdenDespachoSerializer(despacho)
        return Response(serializer.data)

    def create(self, request):
        serializer = CrearOrdenDespachoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        despacho = serializer.save()
        response_serializer = OrdenDespachoSerializer(despacho)
        return Response(response_serializer.data, status=201)
    



class HistorialOrdenDespachoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para ver el historial de cambios de las Órdenes de Despacho.
    """
    queryset = OrdenDespacho.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalOrdenDespachoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_estado_despacho', 'id_repartidor']
    search_fields = ['history_user__usuario', 'id_repartidor__nombre']