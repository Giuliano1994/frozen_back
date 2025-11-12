## trazabilidad/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TrazabilidadViewSet

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
    path('', include(router.urls)),
]