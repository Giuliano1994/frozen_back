from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RecetaViewSet, RecetaMateriaPrimaViewSet

router = DefaultRouter()
router.register(r'recetas', RecetaViewSet)
router.register(r'recetas-materias', RecetaMateriaPrimaViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
