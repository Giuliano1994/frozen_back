from django.shortcuts import render
from stock.models import LoteProduccion
from rest_framework import viewsets, filters
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view  # <- IMPORT IMPORTANTE
from django_filters.rest_framework import DjangoFilterBackend
from stock.services import cantidad_total_disponible_producto,  verificar_stock_y_enviar_alerta


from django_filters.rest_framework import DjangoFilterBackend
from .models import (
    EstadoLoteProduccion,
    EstadoLoteMateriaPrima,
    LoteProduccion,
    LoteMateriaPrima,
    LoteProduccionMateria
)
from .serializers import (
    EstadoLoteProduccionSerializer,
    EstadoLoteMateriaPrimaSerializer,
    LoteProduccionSerializer,
    LoteMateriaPrimaSerializer,
    LoteProduccionMateriaSerializer
)

# ----- Estados -----
class EstadoLoteProduccionViewSet(viewsets.ModelViewSet):
    queryset = EstadoLoteProduccion.objects.all()
    serializer_class = EstadoLoteProduccionSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["descripcion"]
    filterset_fields = ["descripcion"]

class EstadoLoteMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = EstadoLoteMateriaPrima.objects.all()
    serializer_class = EstadoLoteMateriaPrimaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["descripcion"]
    filterset_fields = ["descripcion"]

# ----- Lotes -----
class LoteProduccionViewSet(viewsets.ModelViewSet):
    queryset = LoteProduccion.objects.all()
    serializer_class = LoteProduccionSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_producto__nombre"]
    filterset_fields = ["id_producto", "id_estado_lote_produccion", "fecha_produccion", "fecha_vencimiento"]

class LoteMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = LoteMateriaPrima.objects.all()
    serializer_class = LoteMateriaPrimaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_materia_prima__nombre"]
    filterset_fields = ["id_materia_prima", "id_estado_lote_materia_prima", "fecha_vencimiento"]

class LoteProduccionMateriaViewSet(viewsets.ModelViewSet):
    queryset = LoteProduccionMateria.objects.all()
    serializer_class = LoteProduccionMateriaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_lote_produccion__id_producto__nombre", "id_lote_materia_prima__id_materia_prima__nombre"]
    filterset_fields = ["id_lote_produccion", "id_lote_materia_prima"]



@api_view(["GET"])
def cantidad_total_producto_view(request, id_producto):
    """
    Endpoint que devuelve la cantidad total disponible de un producto.
    """
    total = cantidad_total_disponible_producto(id_producto)
    return Response(
        {"id_producto": id_producto, "cantidad_disponible": total},
        status=status.HTTP_200_OK
    )




@api_view(["GET"])
def verificar_stock_view(request, id_producto):
    """
    Endpoint que verifica stock y envía alerta por correo.
    Recibe parámetro email en query params.
    """
    email = request.query_params.get("email")
    if not email:
        return Response(
            {"error": "Debe especificar el parámetro 'email' en la consulta."},
            status=status.HTTP_400_BAD_REQUEST
        )

    resultado = verificar_stock_y_enviar_alerta(id_producto, email)
    status_code = status.HTTP_200_OK if "error" not in resultado else status.HTTP_404_NOT_FOUND
    return Response(resultado, status=status_code)