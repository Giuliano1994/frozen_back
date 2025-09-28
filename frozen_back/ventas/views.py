from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto
from .serializers import (
    EstadoVentaSerializer,
    ClienteSerializer,
    OrdenVentaSerializer,
    OrdenVentaProductoSerializer,
)

class EstadoVentaViewSet(viewsets.ModelViewSet):
    queryset = EstadoVenta.objects.all()
    serializer_class = EstadoVentaSerializer


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer


class OrdenVentaViewSet(viewsets.ModelViewSet):
    queryset = OrdenVenta.objects.all()
    serializer_class = OrdenVentaSerializer


class OrdenVentaProductoViewSet(viewsets.ModelViewSet):
    queryset = OrdenVentaProducto.objects.all()
    serializer_class = OrdenVentaProductoSerializer



@api_view(['GET'])
def detalle_orden_venta(request, orden_id):
    """
    Devuelve los productos (detalle) de una orden de venta por su ID.
    """
    detalle = OrdenVentaProducto.objects.filter(id_orden_venta_id=orden_id)
    serializer = OrdenVentaProductoSerializer(detalle, many=True)
    return Response(serializer.data)