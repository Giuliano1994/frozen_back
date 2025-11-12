from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TipoProductoViewSet, UnidadViewSet, ProductoViewSet, ProductoLiteListView, ImagenProductoViewSet, ComboViewSet

router = DefaultRouter()
router.register(r'tipos-producto', TipoProductoViewSet)
router.register(r'unidades', UnidadViewSet)
router.register(r'productos', ProductoViewSet)
router.register(r'imagenes-producto', ImagenProductoViewSet)
router.register(r'combos', ComboViewSet, basename='combos') 

urlpatterns = [
    path('', include(router.urls)),
    path("listar/", ProductoLiteListView.as_view(), name="productos-lite"),
]
