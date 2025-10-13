from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EstadoLoteProduccionViewSet,
    EstadoLoteMateriaPrimaViewSet,
    LoteProduccionViewSet,
    LoteMateriaPrimaViewSet,
    LoteProduccionMateriaViewSet,
    agregar_o_crear_lote,
    cantidad_total_producto_view,
    listar_materias_primas,
    restar_cantidad_lote,
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
    path("materias_primas/agregar/", agregar_o_crear_lote, name="agregar_o_crear_lote"),
    path("materias_primas/restar/", restar_cantidad_lote, name="restar_cantidad_lote"),
    path('materiasprimas/', listar_materias_primas, name='listar_materias_primas'),
]