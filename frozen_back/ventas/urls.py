from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EstadoVentaViewSet, ClienteViewSet, OrdenVentaViewSet, OrdenVentaProductoViewSet, detalle_orden_venta  

router = DefaultRouter()
router.register(r'estados-venta', EstadoVentaViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'ordenes-venta', OrdenVentaViewSet)
router.register(r'ordenes-productos', OrdenVentaProductoViewSet)

urlpatterns = [
    path('ordenes-venta/<int:orden_id>/detalle/', detalle_orden_venta, name='detalle_orden_venta'),
    path('', include(router.urls)),
]
