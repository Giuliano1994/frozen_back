from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EstadoVentaViewSet, ClienteViewSet, OrdenVentaViewSet, OrdenVentaProductoViewSet, PrioridadViewSet, ReclamoViewSet, SugerenciaViewSet, crear_orden_venta, detalle_orden_venta, cancelar_orden_view, obtener_facturacion, cambiar_estado_orden_venta, HistorialOrdenVentaViewSet, HistorialNotaCreditoViewSet
from . import views

router = DefaultRouter()
router.register(r'estados-venta', EstadoVentaViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'prioridades', PrioridadViewSet)
router.register(r'ordenes-venta', OrdenVentaViewSet)
router.register(r'ordenes-productos', OrdenVentaProductoViewSet)
router.register(r'reclamos', ReclamoViewSet)
router.register(r'sugerencias', SugerenciaViewSet)
router.register(r'notas-credito', views.NotaCreditoViewSet)
router.register(r'historial-ordenes-venta', HistorialOrdenVentaViewSet, basename='historial-ordenventa'),
router.register(r'historial-notas-credito', HistorialNotaCreditoViewSet, basename='historial-notacredito'),

urlpatterns = [
    path('ordenes-venta/<int:orden_id>/detalle/', detalle_orden_venta, name='detalle_orden_venta'),
    path('ordenes-venta/crear/', views.crear_orden_venta, name = 'crear_orden_venta'),
    path('ordenes-venta/actualizar/', views.actualizar_orden_venta, name = 'actualizar_orden_venta'),
    path('ordenes-venta/listar/', views.listar_ordenes_venta, name = 'listar_ordenes_venta'),
    path("facturacion/<int:id_orden_venta>/", obtener_facturacion, name="obtener_facturacion"),
    path('ordenes/<int:orden_id>/cancelar/', cancelar_orden_view, name='cancelar-orden'),
    path('ordenes_venta/cambiar_estado/', cambiar_estado_orden_venta, name='cambiar_estado_orden_venta'),
    path('', include(router.urls)),
  
]
