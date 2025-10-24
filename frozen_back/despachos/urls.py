from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrdenDespachoViewSet, estadoDespachoViewSet, RepartidorViewSet, despachoOrenVentaViewSet, HistorialOrdenDespachoViewSet

router = DefaultRouter()
router.register(r'estado-despacho', estadoDespachoViewSet)
router.register(r'repartidores', RepartidorViewSet)
router.register(r'despacho-orden-venta', despachoOrenVentaViewSet)
router.register(r'ordenes-despacho', OrdenDespachoViewSet, basename='orden-despacho')
router.register(r'historial-ordenes-despacho', HistorialOrdenDespachoViewSet, basename='historial-ordendespacho')

urlpatterns = [
    path('', include(router.urls)),
]