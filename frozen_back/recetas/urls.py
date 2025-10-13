from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LineasProduccionPorProductoView, RecetaViewSet, RecetaMateriaPrimaViewSet

router = DefaultRouter()
router.register(r'recetas', RecetaViewSet)
router.register(r'recetas-materias', RecetaMateriaPrimaViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path("lineas_por_producto/", LineasProduccionPorProductoView.as_view(), name="lineas-por-producto"),
]

