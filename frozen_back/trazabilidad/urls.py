# trazabilidad/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TrazabilidadViewSet

# Creamos un router
router = DefaultRouter()

# Registramos el ViewSet.
# Usamos r'trazabilidad' como el prefijo de la URL.
# Debemos especificar un 'basename' porque este ViewSet no tiene un 'queryset'.
router.register(r'trazabilidad', TrazabilidadViewSet, basename='trazabilidad')
router.register(r'lotes-produccion', TrazabilidadViewSet, basename='lotes-produccion')

# Las URLs de la API ahora son generadas automáticamente por el router.
urlpatterns = [
    path('', include(router.urls)),
]