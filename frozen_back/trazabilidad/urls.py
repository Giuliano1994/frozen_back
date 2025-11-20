## trazabilidad/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TrazabilidadViewSet, ordenes_por_lote_mp, obtener_lotes_produccion_por_mp, obtener_ordenes_venta_por_lote

# Creamos un router
router = DefaultRouter()

# Registramos el ViewSet UNA SOLA VEZ con la base URL principal: 'trazabilidad'.
# Esto generará los siguientes patrones:
# /trazabilidad/
# /trazabilidad/{pk}/
# /trazabilidad/{pk}/backward/               <-- trace_backward_by_order
# /trazabilidad/hacia-adelante/              <-- trace_forward_by_mp_lote
# /trazabilidad/{pk}/audit/                  <-- trace_op_audit
# /trazabilidad/{pk}/ordenes-venta-asociadas/ <-- obtener_ordenes_venta_por_lote
router.register(r'trazabilidad', TrazabilidadViewSet, basename='trazabilidad')

# Las URLs de la API se incluyen aquí.
urlpatterns = [
    # Quedará como: /trazabilidad/ordenes-por-lote/123/
    path('ordenes-por-lote/<int:id_lote>/', ordenes_por_lote_mp, name='ordenes-por-lote'),
    path('lotes-produccion/por-mp/<int:id_lote_mp>/', obtener_lotes_produccion_por_mp, name='lotes-produccion-por-mp'),
    path('por-lote-produccion/<int:id_lote>/', obtener_ordenes_venta_por_lote),
    path('', include(router.urls)),
]