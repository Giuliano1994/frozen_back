from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import TipoMateriaPrima, MateriaPrima
from .serializers import TipoMateriaPrimaSerializer, MateriaPrimaSerializer

# ------------------------------
# TipoMateriaPrima
# ------------------------------
class TipoMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = TipoMateriaPrima.objects.all()
    serializer_class = TipoMateriaPrimaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["descripcion"]
    search_fields = ["descripcion"]

# ------------------------------
# MateriaPrima
# ------------------------------
class MateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = MateriaPrima.objects.all()
    serializer_class = MateriaPrimaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_tipo_materia_prima", "id_unidad", "nombre"]
    search_fields = ["nombre", "descripcion", "id_tipo_materia_prima__descripcion"]