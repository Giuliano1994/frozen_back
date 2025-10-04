from django.shortcuts import render

from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Receta, RecetaMateriaPrima
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