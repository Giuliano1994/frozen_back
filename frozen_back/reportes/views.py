from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, F, Count
from django.db.models.functions import TruncDate, TruncMonth
from datetime import datetime, timedelta # Asegúrate de importar timedelta si usas el helper

# --- ¡IMPORTANTE! ---
# Ahora importas los modelos desde sus apps correspondientes
from produccion.models import OrdenDeTrabajo, NoConformidad, EstadoOrdenTrabajo
from stock.models import LoteProduccionMateria
from productos.models import Producto
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Count, Value, CharField, FloatField
from django.db.models.functions import TruncDate, Coalesce


# Helper para parsear fechas (puedes mejorarlo)
def parsear_fechas(request):
    """Obtiene fecha_desde y fecha_hasta de los query params."""
    # Valores por defecto (ej. últimos 30 días) - ¡Ajústalos a tu gusto!
    fecha_hasta_str = request.query_params.get('fecha_hasta', datetime.now().strftime('%Y-%m-%d'))
    # Por defecto, 30 días antes de la fecha_hasta
    fecha_desde_str = request.query_params.get('fecha_desde', 
        (datetime.strptime(fecha_hasta_str, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'))

    try:
        # Asegúrate de incluir el final del día en fecha_hasta para los filtros __range
        fecha_desde = datetime.strptime(fecha_desde_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        fecha_hasta = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        return fecha_desde, fecha_hasta
    except ValueError:
        # Manejo de error si las fechas no son válidas
        return None, None


# --- VISTAS DE REPORTES ---

### 1. Reportes de Producción

class ReporteProduccionDiaria(APIView):
    """
    API para gráfico de serie temporal (ej. líneas apiladas).
    Devuelve la cantidad total por día Y POR ESTADO.
    
    Usa 'hora_inicio_programada' para filtrar y agrupar por fecha.
    
    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # 1. Filtramos por RANGO DE FECHAS usando la fecha programada
        query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).select_related(
            'id_estado_orden_trabajo' # Optimización para joins
        )

        # 2. Agregación: Agrupar por día Y por estado
        reporte = query.annotate(
            # Trunca la fecha programada a solo la fecha (día)
            fecha=TruncDate('hora_inicio_programada') 
        ).values(
            'fecha', # Agrupar por la fecha truncada
            # Maneja el caso de que el estado sea NULO
            estado=Coalesce(
                F('id_estado_orden_trabajo__descripcion'), 
                Value('Sin Estado'), 
                output_field=CharField()
            )
        ).annotate(
            # Sumamos la cantidad programada, ya que 'producida' puede ser Nulo
            total_cantidad=Sum('cantidad_programada')
        ).order_by('fecha', 'estado') # Importante para gráficos

        """
        Salida de Ejemplo:
        [
            {"fecha": "2025-10-20", "estado": "Pendiente", "total_cantidad": 500},
            {"fecha": "2025-10-20", "estado": "En Progreso", "total_cantidad": 300},
            {"fecha": "2025-10-21", "estado": "Completada", "total_cantidad": 1500},
            {"fecha": "2025-10-21", "estado": "Pendiente", "total_cantidad": 400}
        ]
        """
        return Response(reporte)


class ReporteProduccionPorProducto(APIView):
    """
    API para gráfico de torta o barras (Pie chart / Bar chart).
    Devuelve el total por producto Y POR ESTADO en un rango de fechas.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. Filtramos por RANGO DE FECHAS usando la fecha programada
        query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).select_related(
            'id_orden_produccion__id_producto', # Optimización
            'id_estado_orden_trabajo'          # Optimización
        )

        # 2. Agregación: Agrupar por producto Y por estado
        reporte = query.values(
            # Agrupar por el nombre/descripción del producto
            producto_nombre=Coalesce(
                F('id_orden_produccion__id_producto__descripcion'),
                Value('Producto Desconocido'),
                output_field=CharField()
            ),
            # Agrupar por la descripción del estado
            estado=Coalesce(
                F('id_estado_orden_trabajo__descripcion'),
                Value('Sin Estado'),
                output_field=CharField()
            )
        ).annotate(
            # Sumamos la cantidad programada
            total_cantidad=Sum('cantidad_programada')
        ).order_by('producto_nombre', 'estado') 

        """
        Salida de Ejemplo:
        [
            {"producto_nombre": "Producto A", "estado": "Pendiente", "total_cantidad": 500},
            {"producto_nombre": "Producto A", "estado": "Completada", "total_cantidad": 4000},
            {"producto_nombre": "Producto B", "estado": "En Progreso", "total_cantidad": 800}
        ]
        """
        return Response(reporte)


### 2. Reporte de Consumo

class ReporteConsumoMateriaPrima(APIView):
    """
    API para gráfico de barras o serie temporal.
    Devuelve la cantidad total de materia prima consumida.
    Usamos 'LoteProduccionMateria' que registra el consumo real.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # Filtramos por la fecha de producción del lote que consumió la materia
        query = LoteProduccionMateria.objects.filter(
            id_lote_produccion__fecha_produccion__range=(fecha_desde, fecha_hasta)
        )

        # Agregación: Agrupar por materia prima y sumar
        reporte = query.values(
            # Accedemos a la descripción de la materia prima
            materia_prima_nombre=F('id_lote_materia_prima__id_materia_prima__descripcion')
        ).annotate(
            total_consumido=Sum('cantidad_usada')
        ).order_by('-total_consumido')

        # Salida: [{"materia_prima_nombre": "Acero", "total_consumido": 10000}, ...]
        return Response(reporte)


### 3. Reporte de Desperdicio

class ReporteDesperdicioPorCausa(APIView):
    """
    API para gráfico de torta o barras (Pareto).
    Muestra el total desperdiciado agrupado por la razón (descripción).

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # Filtramos por la fecha de la Orden de Producción asociada
        # (NoConformidad no tiene fecha propia)
        query = NoConformidad.objects.filter(
            id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta) # O usa fecha_inicio
        )

        # Agregación: Agrupar por la descripción de la no conformidad
        reporte = query.values(
            razon=F('descripcion')
        ).annotate(
            total_desperdiciado=Sum('cant_desperdiciada')
        ).order_by('-total_desperdiciado')

        # Salida: [{"razon": "Falla de máquina", "total_desperdiciado": 150}, ...]
        return Response(reporte)


class ReporteDesperdicioPorProducto(APIView):
    """
    API para gráfico de barras.
    Muestra el total desperdiciado agrupado por producto.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        query = NoConformidad.objects.filter(
            id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        )

        # Agregación: Agrupar por producto
        reporte = query.values(
            producto_nombre=F('id_orden_produccion__id_producto__descripcion')
        ).annotate(
            total_desperdiciado=Sum('cant_desperdiciada')
        ).order_by('-total_desperdiciado')

        # Salida: [{"producto_nombre": "Producto B", "total_desperdiciado": 80}, ...]
        return Response(reporte)
    

class ReporteTasaDeDesperdicio(APIView):

    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # 1. CALCULAR EL TOTAL DESPERDICIADO (NUMERADOR)
        total_desperdiciado_query = NoConformidad.objects.filter(
            id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_desperdiciado=Coalesce(
                Sum('cant_desperdiciada'), 
                Value(0.0), 
                output_field=FloatField() 
            )
        )
        total_desperdiciado = total_desperdiciado_query.get('total_desperdiciado', 0.0)

        # 2. CALCULAR EL TOTAL PRODUCIDO/PROGRAMADO (DENOMINADOR)
        total_producido_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_programado=Coalesce(
                Sum('cantidad_programada'), 
                Value(0.0),
                output_field=FloatField() 
            )
        )
        total_programado = total_producido_query.get('total_programado', 0.0)
        
        # ... (resto del cálculo de la tasa) ...
        tasa_desperdicio = 0.0
        
        if total_programado > 0:
            tasa_desperdicio = (total_desperdiciado / total_programado) * 100.0

        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_programado": total_programado,
            "total_desperdiciado": total_desperdiciado,
            "tasa_desperdicio_porcentaje": round(tasa_desperdicio, 2)
        }

        return Response(resultado)