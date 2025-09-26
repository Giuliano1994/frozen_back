from django.urls import path
from . import views

urlpatterns = [
    path('empleados/', views.lista_empleados, name='lista_empleados'),
    path('menu-rol/<str:nombreRol>/', views.menu_rol, name='menu_rol'),
    ]