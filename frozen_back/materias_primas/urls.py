from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TipoMateriaPrimaViewSet, MateriaPrimaViewSet

router = DefaultRouter()
router.register(r'tipos', TipoMateriaPrimaViewSet)
router.register(r'materias', MateriaPrimaViewSet)

urlpatterns = [
    path('', include(router.urls)),
]