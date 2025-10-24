from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EstadoLineaProduccionViewSet,
    EstadoOrdenProduccionViewSet,
    LineaProduccionViewSet,
    OrdenProduccionViewSet,
    NoConformidadViewSet,
    HistorialOrdenProduccionViewSet
)

router = DefaultRouter()
router.register(r'estados', EstadoOrdenProduccionViewSet)
router.register(r'lineas', LineaProduccionViewSet)
router.register(r'ordenes', OrdenProduccionViewSet)
router.register(r'noconformidades', NoConformidadViewSet)
router.register(r'estado_linea_produccion', EstadoLineaProduccionViewSet)  
router.register(r'historial-ordenes-produccion', HistorialOrdenProduccionViewSet, basename='historial-ordenproduccion')

urlpatterns = [
    path('', include(router.urls)),
]