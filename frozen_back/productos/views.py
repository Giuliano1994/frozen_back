from django.shortcuts import render
from rest_framework import viewsets, generics

from .models import TipoProducto, Unidad, Producto, ImagenProducto
from .serializers import TipoProductoSerializer, UnidadSerializer, ProductoSerializer, ProductoLiteSerializer, ImagenProductoSerializer, ProductoDetalleSerializer


class TipoProductoViewSet(viewsets.ModelViewSet):
    queryset = TipoProducto.objects.all()
    serializer_class = TipoProductoSerializer


class UnidadViewSet(viewsets.ModelViewSet):
    queryset = Unidad.objects.all()
    serializer_class = UnidadSerializer


# ACTUALIZADO: Tu ProductoViewSet
class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    # serializer_class = ProductoSerializer # <-- Borramos esto

    # NUEVO: Método para elegir el serializador según la acción
    def get_serializer_class(self):
        # Si la acción es 'retrieve' (pedir 1 producto por ID)
        if self.action in ['retrieve', 'list']:
            return ProductoDetalleSerializer  # <-- Usa el que tiene imágenes
        
        # Para todas las demás acciones ('list', 'create', 'update', 'partial_update')
        return ProductoSerializer # <-- Usa el normal (sin imágenes)


# NUEVO: Un ViewSet para poder CREAR y BORRAR imágenes
class ImagenProductoViewSet(viewsets.ModelViewSet):
    queryset = ImagenProducto.objects.all()
    serializer_class = ImagenProductoSerializer

class ProductoLiteListView(generics.ListAPIView):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer