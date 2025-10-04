from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TipoProductoViewSet, UnidadViewSet, ProductoViewSet, ProductoLiteListView

router = DefaultRouter()
router.register(r'tipos-producto', TipoProductoViewSet)
router.register(r'unidades', UnidadViewSet)
router.register(r'productos', ProductoViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path("listar/", ProductoLiteListView.as_view(), name="productos-lite"),
]
