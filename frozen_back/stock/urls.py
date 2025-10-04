from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EstadoLoteProduccionViewSet,
    EstadoLoteMateriaPrimaViewSet,
    LoteProduccionViewSet,
    LoteMateriaPrimaViewSet,
    LoteProduccionMateriaViewSet
)

router = DefaultRouter()
router.register(r'estado-lotes-produccion', EstadoLoteProduccionViewSet)
router.register(r'estado-lotes-materias', EstadoLoteMateriaPrimaViewSet)
router.register(r'lotes-produccion', LoteProduccionViewSet)
router.register(r'lotes-materias', LoteMateriaPrimaViewSet)
router.register(r'lotes-produccion-materias', LoteProduccionMateriaViewSet)

urlpatterns = [
    path('', include(router.urls)),
]