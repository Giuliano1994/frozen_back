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

     path('produccion/cumplimiento-plan/', 
         views.ReporteCumplimientoPlan.as_view(), 
         name='reporte-cumplimiento-plan'),

     path('produccion/cumplimiento-mensual/', 
         views.ReporteCumplimientoPlanMensual.as_view(), 
         name='reporte-cumplimiento-mensual'),

     path('produccion/cumplimiento-semanal/', 
        views.ReporteCumplimientoPlanSemanal.as_view(), 
        name='reporte_cumplimiento_semanal'),

     path('produccion/lineas-produccion/', 
         views.LineasProduccionYEstado.as_view(), 
         name='reporte-lineas-produccion'),

     path('oee/calidad/', 
         views.ReporteFactorCalidadOEE.as_view(), 
         name='reporte-calidad-oee'),

     path('oee/disponibilidad/', 
         views.ReporteDisponibilidadAjustada.as_view(), 
         name='reporte-disponibilidad-oee'),

     path('oee/rendimiento/', 
         views.ReporteFactorRendimientoOEE.as_view(),
         name='reporte-rendimiento-oee'),

    path('oee/', 
         views.ReporteOEEGeneral.as_view(),
         name='reporte-oee'),

    path('ventas/ventas-por-tipo/', 
         views.ReporteVolumenPorTipo.as_view(),
         name='ventas-por-tipo'),

    path('ventas/tiempo-ciclo-venta/', 
         views.ReporteTiempoCicloVenta.as_view(),
         name='reporte-tiempo-ciclo-venta'),

    path('ventas/cumplimiento-fecha/', 
         views.ReporteCumplimientoFecha.as_view(),
         name='ventas-cumplimiento-fecha'),

    path('ventas/total-dinero/', 
         views.ReporteTotalDineroVentas.as_view(),
         name='ventas-total-dinero'),

    path('ventas/valor-pedido-promedio/', 
         views.ReporteValorPedidoPromedio.as_view(),
         name='ventas-valor-promedio'),

    path('ventas/productos-por-venta/', 
         views.ReporteProductosPorVenta.as_view(),
         name='ventas-productos'),

    path('ventas/ventas-por-tipo-producto/', 
         views.ReporteDistribucionProductoPorTipo.as_view(),
         name='ventas-por-tipo-producto'),
]