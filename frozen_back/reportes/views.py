from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, F, Count
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek, ExtractYear
from datetime import datetime, timedelta # Asegúrate de importar timedelta si usas el helper


# --- ¡IMPORTANTE! ---
# Ahora importas los modelos desde sus apps correspondientes
from produccion.models import OrdenDeTrabajo, NoConformidad, EstadoOrdenTrabajo, LineaProduccion, estado_linea_produccion
from stock.models import LoteProduccionMateria
from productos.models import Producto
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Count, Value, CharField, FloatField, Q, DateField, Case, When, BooleanField
from django.db.models.functions import TruncDate, Coalesce, Cast

from django.utils import timezone


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
    Muestra el total desperdiciado agrupado por la causa estandarizada (TipoNoConformidad).

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. FILTRADO: Usamos la fecha de creación de la Orden de Producción (OP), 
        #    accediendo a través de la Orden de Trabajo (OT).
        query = NoConformidad.objects.filter(
            # Cadena de FKs: NC -> OT -> OP -> fecha_creacion
            id_orden_trabajo__id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        )

        # 2. AGRUPACIÓN: Agrupar por el Tipo de No Conformidad (causa estandarizada)
        reporte = query.values(
            # Agrupamos por el nombre del TipoNoConformidad
            causa=F('id_tipo_no_conformidad__nombre') 
        ).annotate(
            total_desperdiciado=Sum('cant_desperdiciada')
        ).order_by('-total_desperdiciado')

        # Salida: [{"causa": "Falla de Empaque", "total_desperdiciado": 150}, ...]
        return Response(reporte)


class ReporteDesperdicioPorProducto(APIView):
    """
    API para gráfico de barras.
    Muestra el total desperdiciado agrupado por producto,
    utilizando la cadena de FK: NoConformidad -> OrdenDeTrabajo -> OrdenProduccion -> Producto.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. FILTRADO: Usamos la fecha_creacion de la Orden de Producción,
        #    accediendo a través de la Orden de Trabajo.
        query = NoConformidad.objects.filter(
            # Cadena de FKs: NC -> OT -> OP -> fecha_creacion
            id_orden_trabajo__id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        )

        # 2. AGRUPACIÓN: Agrupar por producto, accediendo a la descripción del producto
        #    a través de la Orden de Producción.
        reporte = query.values(
            # Cadena de FKs: NC -> OT -> OP -> Producto -> descripción
            producto_nombre=F('id_orden_trabajo__id_orden_produccion__id_producto__descripcion')
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
    

class ReporteCumplimientoPlan(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) por Cantidad (Volumen).
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request) 
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)
        
        # 1. CALCULAR EL TOTAL PLANIFICADO (DENOMINADOR)
        total_planificado_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField())
        )
        total_planificado = total_planificado_query.get('total_planificado', 0.0)

        # 2. CALCULAR LA CANTIDAD CUMPLIDA A TIEMPO (NUMERADOR)
        ots_anotadas = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta) 
        ).annotate(
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    dia_fin_real=F('dia_fin_programado'),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        total_cumplido_query = ots_anotadas.filter(
            cumplio_fecha=True, 
            id_estado_orden_trabajo__descripcion='Completada', 
            hora_fin_real__isnull=False, 
        ).aggregate(
            total_cumplido_adherencia=Coalesce(
                Sum('cantidad_producida'), 
                Value(0.0),
                output_field=FloatField()
            )
        )
        total_cumplido = total_cumplido_query.get('total_cumplido_adherencia', 0.0)

        # 3. CÁLCULO DEL PCA y Respuesta
        pcp = 0.0
        if total_planificado > 0:
            pcp = (total_cumplido / total_planificado) * 100.0

        # CORRECCIÓN DE ERROR: Usar timedelta directamente
        fecha_fin_respuesta = (fecha_hasta - timedelta(days=1)).strftime('%Y-%m-%d')
        
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_fin_respuesta,
            "total_planificado": total_planificado,
            "total_cantidad_cumplida_a_tiempo": total_cumplido,
            "porcentaje_cumplimiento_adherencia": round(pcp, 2)
        }

        return Response(resultado)
    
class ReporteCumplimientoPlanMensual(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) agrupado por mes.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)

        # 1. ANOTAR LAS OTs con el mes, año y si cumplió la fecha programada
        ots_base = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta),
        ).annotate(
            # Campo para agrupar: Mes de la hora de inicio programada
            mes_reporte=TruncMonth('hora_inicio_programada'),
            
            # Campos para verificar cumplimiento
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    # Criterio de cumplimiento: Día de fin real <= Día de fin programado
                    dia_fin_real__lte=F('dia_fin_programado'), 
                    # El estado debe ser 'Completada' y la hora_fin_real no nula
                    id_estado_orden_trabajo__descripcion='Completada',
                    hora_fin_real__isnull=False,
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        # 2. AGREGAR Y AGRUPAR POR MES
        resultados_agrupados = ots_base.values('mes_reporte').annotate(
            # Denominador: Total planificado para ese mes
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField()),
            
            # Numerador: Suma de la cantidad_programada SOLO de las que cumplieron
            total_cumplido_adherencia=Coalesce(
                Sum(
                    Case(
                        When(cumplio_fecha=True, then='cantidad_producida'),
                        default=Value(0),
                        output_field=FloatField()
                    )
                ), 
                Value(0.0),
                output_field=FloatField()
            )
        ).order_by('mes_reporte')
        
        # 3. Formatear resultados y calcular PCA por mes
        reporte = []
        for item in resultados_agrupados:
            planificado = item['total_planificado']
            cumplido = item['total_cumplido_adherencia']
            
            # Cálculo del PCA mensual
            pca_mensual = (cumplido / planificado * 100) if planificado > 0 else 0.0
            
            reporte.append({
                "mes": item['mes_reporte'].strftime('%Y-%m'), 
                "total_planificado": round(planificado, 2),
                "total_cumplido_adherencia": round(cumplido, 2),
                "pca_mensual": round(pca_mensual, 2)
            })
            
        return Response(reporte)
    
class ReporteCumplimientoPlanSemanal(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) agrupado por semana.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)

        # 1. ANOTAR LAS OTs con la semana y si cumplió la fecha programada
        ots_base = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta),
        ).annotate(
            # Campo para agrupar: Trunca a la fecha de inicio de la semana
            semana_reporte=TruncWeek('hora_inicio_programada'),
            
            # Campos para verificar cumplimiento
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    # Criterio de cumplimiento: Día de fin real <= Día de fin programado
                    dia_fin_real__lte=F('dia_fin_programado'), 
                    # El estado debe ser 'Completada' y la hora_fin_real no nula
                    id_estado_orden_trabajo__descripcion='Completada',
                    hora_fin_real__isnull=False,
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        # 2. AGREGAR Y AGRUPAR POR SEMANA
        resultados_agrupados = ots_base.values('semana_reporte').annotate(
            # Denominador: Total planificado para esa semana
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField()),
            
            # Numerador: Suma de la cantidad_programada SOLO de las que cumplieron
            total_cumplido_adherencia=Coalesce(
                Sum(
                    Case(
                        When(cumplio_fecha=True, then='cantidad_producida'),
                        default=Value(0),
                        output_field=FloatField()
                    )
                ), 
                Value(0.0),
                output_field=FloatField()
            )
        ).order_by('semana_reporte')
        
        # 3. Formatear resultados y calcular PCA por semana
        reporte = []
        for item in resultados_agrupados:
            planificado = item['total_planificado']
            cumplido = item['total_cumplido_adherencia']
            
            # Cálculo del PCA semanal
            pca_semanal = (cumplido / planificado * 100) if planificado > 0 else 0.0
            
            # El resultado de TruncWeek es un objeto datetime, lo formateamos a YYYY-MM-DD (fecha de inicio de la semana)
            reporte.append({
                "semana_inicio": item['semana_reporte'].strftime('%Y-%m-%d'),
                "total_planificado": round(planificado, 2),
                "total_cumplido_adherencia": round(cumplido, 2),
                "pca_semanal": round(pca_semanal, 2)
            })
            
        return Response(reporte)
    
class LineasProduccionYEstado(APIView):
    """
    Devuelve la lista de TODAS las líneas de producción, mostrando su nombre 
    y la descripción de su estado actual, sin importar si están activas o no.
    """
    def get(self, request, *args, **kwargs):
        
        # Obtenemos TODAS las líneas de producción
        lineas = LineaProduccion.objects.all().values(
            # Proyectamos el nombre de la línea
            nombre_linea=F('descripcion'), 
            
            # Obtenemos la descripción del estado a través de la clave foránea.
            # Usamos Coalesce para manejar si, hipotéticamente, el estado fuera NULL
            estado_actual=Coalesce(
                F('id_estado_linea_produccion__descripcion'), 
                Value('Sin Estado Asignado'),
                output_field=CharField()
            )
        ).order_by('nombre_linea')
        
        """
        Salida de Ejemplo:
        [
            {"nombre_linea": "Línea Ensamblaje A", "estado_actual": "Activa"},
            {"nombre_linea": "Línea Corte Láser", "estado_actual": "Parada"},
            {"nombre_linea": "Línea Empaque", "estado_actual": "Mantenimiento"}
        ]
        """
        return Response(list(lineas))
    
class ReporteFactorCalidadOEE(APIView):
    """
    API para calcular el Factor de Calidad del OEE.
    Calidad = ((Total Programado - Total Desperdiciado) / Total Programado) * 100
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # 1. CALCULAR EL TOTAL DESPERDICIADO (PÉRDIDAS)
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

        # 2. CALCULAR EL TOTAL PROGRAMADO (VOLUMEN)
        # Lo usamos como el 'Total Producido' en este contexto para el cálculo del ratio.
        total_programado_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_programado=Coalesce(
                Sum('cantidad_programada'), 
                Value(0.0),
                output_field=FloatField()
            )
        )
        total_programado = total_programado_query.get('total_programado', 0.0)

        # 3. CÁLCULO DEL FACTOR CALIDAD
        factor_calidad = 0.0
        
        if total_programado > 0:
            # Piezas Buenas = Total Programado - Total Desperdiciado
            piezas_buenas = total_programado - total_desperdiciado
            
            # Factor Calidad = (Piezas Buenas / Total Programado) * 100
            factor_calidad = (piezas_buenas / total_programado) * 100.0

        # 4. PREPARAR RESPUESTA
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_programado": total_programado,
            "total_desperdiciado": total_desperdiciado,
            "factor_calidad_oee": round(factor_calidad, 2) # Porcentaje del 0 al 100
        }

        return Response(resultado)