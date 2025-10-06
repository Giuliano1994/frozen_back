from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EstadoLoteProduccionViewSet,
    EstadoLoteMateriaPrimaViewSet,
    LoteProduccionViewSet,
    LoteMateriaPrimaViewSet,
    LoteProduccionMateriaViewSet,
    cantidad_total_producto_view,
    verificar_stock_view
)

router = DefaultRouter()
router.register(r'estado-lotes-produccion', EstadoLoteProduccionViewSet)
router.register(r'estado-lotes-materias', EstadoLoteMateriaPrimaViewSet)
router.register(r'lotes-produccion', LoteProduccionViewSet)
router.register(r'lotes-materias', LoteMateriaPrimaViewSet)
router.register(r'lotes-produccion-materias', LoteProduccionMateriaViewSet)
router.register(r'cantidad-disponible-producto', LoteProduccionViewSet, basename='cantidad-disponible-producto')

urlpatterns = [
    path('', include(router.urls)),
    path('cantidad-disponible/<int:id_producto>/', cantidad_total_producto_view),
    path('verificar-stock/<int:id_producto>/', verificar_stock_view),
]