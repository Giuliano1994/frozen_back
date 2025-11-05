from django.urls import path
from . import views # o .api_views si usaste ese nombre

urlpatterns = [
    # Nota cómo ahora las rutas son relativas a la app
    # Ya no necesitas 'api/reportes/' aquí
    
    path('produccion/diaria/', 
         views.ReporteProduccionDiaria.as_view(), 
         name='reporte-produccion-diaria'),
    
    path('produccion/por_producto/', 
         views.ReporteProduccionPorProducto.as_view(), 
         name='reporte-produccion-producto'),
         
    path('consumo/materia_prima/', 
         views.ReporteConsumoMateriaPrima.as_view(), 
         name='reporte-consumo-materia'),
         
    path('desperdicio/por_causa/', 
         views.ReporteDesperdicioPorCausa.as_view(), 
         name='reporte-desperdicio-causa'),

    path('desperdicio/por_producto/', 
         views.ReporteDesperdicioPorProducto.as_view(), 
         name='reporte-desperdicio-producto'),

     path('desperdicio/tasa/', 
         views.ReporteTasaDeDesperdicio.as_view(), 
         name='reporte-desperdicio-tasa'),
]