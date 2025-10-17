from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TipoProductoViewSet, UnidadViewSet, ProductoViewSet, ProductoLiteListView, ImagenProductoViewSet

router = DefaultRouter()
router.register(r'tipos-producto', TipoProductoViewSet)
router.register(r'unidades', UnidadViewSet)
router.register(r'productos', ProductoViewSet)
router.register(r'imagenes-producto', ImagenProductoViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path("listar/", ProductoLiteListView.as_view(), name="productos-lite"),
]
