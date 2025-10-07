from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EstadoVentaViewSet, ClienteViewSet, OrdenVentaViewSet, OrdenVentaProductoViewSet, PrioridadViewSet, crear_orden_venta, detalle_orden_venta, cambiar_estado_orden_venta  
from . import views

router = DefaultRouter()
router.register(r'estados-venta', EstadoVentaViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'prioridades', PrioridadViewSet)
router.register(r'ordenes-venta', OrdenVentaViewSet)
router.register(r'ordenes-productos', OrdenVentaProductoViewSet)

urlpatterns = [
    path('ordenes-venta/<int:orden_id>/detalle/', detalle_orden_venta, name='detalle_orden_venta'),
    path('ordenes-venta/crear/', views.crear_orden_venta, name = 'crear_orden_venta'),
    path('ordenes-venta/actualizar/', views.actualizar_orden_venta, name = 'actualizar_orden_venta'),
    path('ordenes-venta/listar/', views.listar_ordenes_venta, name = 'listar_ordenes_venta'),
    path('ordenes_venta/cambiar_estado/', cambiar_estado_orden_venta, name='cambiar_estado_orden_venta'),
    path('', include(router.urls)),
  

]
