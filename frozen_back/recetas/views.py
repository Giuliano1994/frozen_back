from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from produccion.models import LineaProduccion
from .models import ProductoLinea, Receta, RecetaMateriaPrima
from .serializers import RecetaSerializer, RecetaMateriaPrimaSerializer

# ------------------------------
# Receta
# ------------------------------
class RecetaViewSet(viewsets.ModelViewSet):
    queryset = Receta.objects.all()
    serializer_class = RecetaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_producto", "descripcion"]
    search_fields = ["descripcion", "id_producto__nombre"]

# ------------------------------
# RecetaMateriaPrima
# ------------------------------
class RecetaMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = RecetaMateriaPrima.objects.all()
    serializer_class = RecetaMateriaPrimaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_receta", "id_materia_prima"]
    search_fields = ["id_materia_prima__nombre"]

class LineasProduccionPorProductoView(APIView):
    """
    Devuelve todas las líneas de producción asociadas a un producto,
    recibiendo el id_producto por JSON.
    """

    def post(self, request):
        id_producto = request.data.get("id_producto")

        if not id_producto:
            return Response(
                {"error": "Debe enviar 'id_producto' en el cuerpo del JSON."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Buscar las líneas asociadas al producto
        lineas_ids = ProductoLinea.objects.filter(
            id_producto=id_producto
        ).values_list("id_linea_produccion", flat=True)

        # Obtener las descripciones de esas líneas
        lineas = LineaProduccion.objects.filter(
            id_linea_produccion__in=lineas_ids
        ).values("id_linea_produccion", "descripcion")

        return Response(list(lineas), status=status.HTTP_200_OK)