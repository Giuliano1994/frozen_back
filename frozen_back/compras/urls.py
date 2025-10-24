from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import orden_compra_materia_primaViewSet, ordenCompraViewSet, estadoOrdenCompraViewSet, orden_compra_produccionViewSet, HistorialOrdenCompraViewSet

router = DefaultRouter()
router.register(r'estados', estadoOrdenCompraViewSet)
router.register(r'ordenes-compra', ordenCompraViewSet)
router.register(r'orden-compra-produccion', orden_compra_produccionViewSet, basename='orden-compra-produccion')
router.register(r'compra-materia', orden_compra_materia_primaViewSet, basename='orden-compra-materia')
router.register(r'historial-ordenes-compra', HistorialOrdenCompraViewSet, basename='historial-ordencompra')

urlpatterns = [
    path('', include(router.urls)),
]