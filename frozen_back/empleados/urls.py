from django.urls import path
from . import views

urlpatterns = [

    #lista todos los empleados
    path('empleados/', views.lista_empleados, name='lista_empleados'),

    #comprueba rol del empleado
    path('menu-rol/<str:nombreRol>/', views.menu_rol, name='menu_rol'),

    #crear empleado nuevo
    path('empleados/crear/', views.crear_empleado, name='crear_empleado'),
    
    ]