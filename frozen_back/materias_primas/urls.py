from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProveedorViewSet, TipoMateriaPrimaViewSet, MateriaPrimaViewSet

router = DefaultRouter()
router.register(r'tipos', TipoMateriaPrimaViewSet)
router.register(r'materias', MateriaPrimaViewSet)
router.register(r'proveedores', ProveedorViewSet)

urlpatterns = [
    path('', include(router.urls)),
]