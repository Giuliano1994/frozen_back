from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, filters
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