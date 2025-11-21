from django.urls import path
from . import views

urlpatterns = [
    # Registra la vista en la URL 'api/planificacion/ejecutar/'
    path('planificacion/', views.ejecutar_planificacion_view, name='ejecutar-planificacion'),
    path('replanificar/', views.replanificar_produccion_view, name='replanificar_produccion'),
    path('ejecutar-mrp/', views.ejecutar_planificador_view, name='ejecutar-mrp'),
    path(
        'calendario/', 
        views.CalendarioPlanificacionView.as_view(), 
        name='calendario_planificacion_feed'
    ),
    path('replanificar-ops-por-capacidad/', views.replanificar_capacidad_view, name='replanificar-ops-por-capacidad'),

]