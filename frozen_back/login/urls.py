from django.urls import path
from . import views

urlpatterns = [
    #fichar empleado por rostro
    path('fichaje/', views.fichar_empleado_por_rostro, name='fichar_empleado_por_rostro'),

    #login de empleado con usuario-contraseña
    path('login/', views.login, name='login'),

    path('login_ecommerce/', views.login_ecommerce, name='login_para_ecommerce')
]