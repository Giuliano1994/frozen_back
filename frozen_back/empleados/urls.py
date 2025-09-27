from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views


router = DefaultRouter()
router.register(r'departamentos', views.DepartamentoViewSet)
router.register(r'turnos', views.TurnoViewSet)
router.register(r'faceid', views.FaceIDViewSet)
router.register(r'roles', views.RolViewSet)
router.register(r'fichadas', views.FichadaViewSet)
router.register(r'permisos', views.PermisoViewSet)
router.register(r'rol-permisos', views.RolPermisoViewSet)

urlpatterns = [
    # endpoints custom para empleados
    path('empleados/', views.lista_empleados, name='lista_empleados'),
    path('empleados/crear/', views.crear_empleado, name='crear_empleado'),
    path('menu-rol/<str:nombreRol>/', views.menu_rol, name='menu_rol'),
    
    path('permisos-rol/<str:nombreRol>/', views.permisos_por_rol, name='permisos_por_rol'),
    # todos los demás CRUD por router
    path('', include(router.urls)),
]