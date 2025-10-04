from django.shortcuts import render
from rest_framework import viewsets, generics

from .models import TipoProducto, Unidad, Producto
from .serializers import TipoProductoSerializer, UnidadSerializer, ProductoSerializer, ProductoLiteSerializer


class TipoProductoViewSet(viewsets.ModelViewSet):
    queryset = TipoProducto.objects.all()
    serializer_class = TipoProductoSerializer


class UnidadViewSet(viewsets.ModelViewSet):
    queryset = Unidad.objects.all()
    serializer_class = UnidadSerializer


class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer


class ProductoLiteListView(generics.ListAPIView):
    queryset = Producto.objects.all()
    serializer_class = ProductoLiteSerializer