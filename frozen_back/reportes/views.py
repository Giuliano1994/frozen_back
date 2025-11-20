from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from django.db.models import Sum, F, Count, fields, Subquery, OuterRef, Avg
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek, ExtractYear, ExtractDay
from datetime import datetime, timedelta # Asegúrate de importar timedelta si usas el helper
from dateutil.relativedelta import relativedelta

# --- ¡IMPORTANTE! ---
# Ahora importas los modelos desde sus apps correspondientes
from ventas.models import OrdenVenta, OrdenVentaProducto
from recetas.models import ProductoLinea
from produccion.models import OrdenDeTrabajo, NoConformidad, EstadoOrdenTrabajo, LineaProduccion, PausaOT, estado_linea_produccion
from stock.models import LoteProduccionMateria
from productos.models import Producto
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Count, Value, CharField, FloatField, Q, DateField, Case, When, BooleanField, ExpressionWrapper, DurationField
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
    """
    Calcula la Tasa de Desperdicio (Total Desperdiciado / Total Programado de OTs Completadas)
    basándose ÚNICAMENTE en las Órdenes de Trabajo que han sido Completadas.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # --- 0. Definir el conjunto base de OTs Completadas en el rango de fecha ---
        # Filtramos las OTs que terminaron dentro del rango o que iniciaron en el rango y se completaron
        ots_completadas = OrdenDeTrabajo.objects.filter(
            id_estado_orden_trabajo__descripcion='Completada',  # Filtro esencial
            hora_inicio_programada__range=rango_fecha_filtro
        )

        # 1. CALCULAR EL TOTAL DESPERDICIADO (NUMERADOR)
        # 🚨 CAMBIO: Filtramos las No Conformidades que pertenecen a las OTs COMPLETADAS
        total_desperdiciado_query = NoConformidad.objects.filter(
            # Filtra las NCs que tienen una OT cuya hora_inicio_programada cae en el rango
            id_orden_trabajo__hora_inicio_programada__range=rango_fecha_filtro,
            # Filtra las NCs cuya OT está en estado 'Completada'
            id_orden_trabajo__id_estado_orden_trabajo__descripcion='Completada' 
        ).aggregate(
            total_desperdiciado=Coalesce(
                Sum('cant_desperdiciada'), 
                Value(0.0), 
                output_field=FloatField() 
            )
        )
        total_desperdiciado = total_desperdiciado_query.get('total_desperdiciado', 0.0)

        # 2. CALCULAR EL TOTAL PROGRAMADO (DENOMINADOR)
        # 🚨 CAMBIO: Sumamos SOLO la cantidad programada de las OTs Completadas
        total_producido_query = ots_completadas.aggregate(
            total_programado=Coalesce(
                Sum('cantidad_programada'), 
                Value(0.0),
                output_field=FloatField() 
            )
        )
        total_programado = total_producido_query.get('total_programado', 0.0)
        
        # 3. CÁLCULO DE LA TASA
        tasa_desperdicio = 0.0
        
        if total_programado > 0:
            # Tasa de desperdicio = (Desperdiciado total / Programado en OTs completadas) * 100
            tasa_desperdicio = (total_desperdiciado / total_programado) * 100.0

        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_programado_completado": total_programado,
            "total_desperdiciado": total_desperdiciado,
            "tasa_desperdicio_porcentaje": round(tasa_desperdicio, 2)
        }

        return Response(resultado)
    

class ReporteCumplimientoPlan(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) por Cantidad (Volumen).
    """
    def get(self, request, *args, **kwargs):
        # NOTA: parsear_fechas debe devolver objetos datetime/date, y generalmente 
        # para rangos de fechas (A, B) se filtra desde A 00:00:00 hasta B 23:59:59.
        fecha_desde, fecha_hasta = parsear_fechas(request) 
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)
        
        # 1. FILTRO BASE: Seleccionamos todas las OT cuyo CUMPLIMIENTO estaba PROGRAMADO
        # dentro del rango de fechas solicitado.
        base_query = OrdenDeTrabajo.objects.filter(
            # Filtramos por la fecha de fin programada, ya que es el criterio de adherencia
            hora_fin_programada__range=(fecha_desde, fecha_hasta)
        )
        
        # 2. CALCULAR EL TOTAL PLANIFICADO (DENOMINADOR)
        total_planificado_query = base_query.aggregate(
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField())
        )
        total_planificado = total_planificado_query.get('total_planificado', 0.0)

        # 3. ANOTAR CUMPLIMIENTO A TIEMPO (Lógica de Adherencia)
        # La adherencia se cumple si la hora_fin_real es MENOR o IGUAL a la hora_fin_programada
        # Y si el estado es 'Completada'.
        ots_anotadas = base_query.annotate(
            # NOTA: Comparamos las horas/timestamps, no solo las fechas, para mayor precisión
            cumplio_adherencia=Case(
                When(
                    # La OT debe estar Completada Y haber terminado A TIEMPO
                    id_estado_orden_trabajo__descripcion='Completada',
                    hora_fin_real__lte=F('hora_fin_programada'),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        # 4. CALCULAR LA CANTIDAD CUMPLIDA A TIEMPO (NUMERADOR)
        # Sumamos la cantidad producida SÓLO de las OT que cumplieron la adherencia.
        total_cumplido_query = ots_anotadas.filter(
            cumplio_adherencia=True,
            # También verificamos que se haya registrado una cantidad (seguridad)
            cantidad_producida__isnull=False
        ).aggregate(
            total_cumplido_adherencia=Coalesce(
                Sum('cantidad_producida'), 
                Value(0.0),
                output_field=FloatField()
            )
        )
        total_cumplido = total_cumplido_query.get('total_cumplido_adherencia', 0.0)

        # 5. CÁLCULO DEL PCA y Respuesta
        pcp = 0.0
        if total_planificado > 0:
            pcp = (total_cumplido / total_planificado) * 100.0

        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            # Retornamos la fecha_hasta tal cual se recibió/parseó.
            "fecha_hasta": fecha_hasta.strftime('%Y-%M-%d'), 
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
            ),
            id_linea=F('id_linea_produccion')
            
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
    
# ====================================================================
# 1. FACTOR DE CALIDAD
# ====================================================================

class ReporteFactorCalidadOEE(APIView):
    """ API para calcular el Factor de Calidad del OEE (Producción Bruta - Desperdicio). """
    
    def _calculate_factor_calidad(self, fecha_desde, fecha_hasta):
        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # 1. CALCULAR LA PRODUCCIÓN BRUTA TOTAL (VOLUMEN REAL)
        produccion_bruta_total_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=rango_fecha_filtro,
            id_estado_orden_trabajo__descripcion='Completada'
        ).aggregate(
            produccion_bruta_total=Coalesce(Sum('produccion_bruta'), Value(0.0), output_field=FloatField())
        )
        produccion_bruta_total = produccion_bruta_total_query.get('produccion_bruta_total', 0.0)

        # 2. CALCULAR EL TOTAL DESPERDICIADO (PÉRDIDAS)
        total_desperdiciado_query = NoConformidad.objects.filter(
            id_orden_trabajo__hora_inicio_programada__range=rango_fecha_filtro,
            id_orden_trabajo__id_estado_orden_trabajo__descripcion='Completada'
        ).aggregate(
            total_desperdiciado=Coalesce(Sum('cant_desperdiciada'), Value(0.0), output_field=FloatField())
        )
        total_desperdiciado = total_desperdiciado_query.get('total_desperdiciado', 0.0)

        # 3. CÁLCULO DEL FACTOR CALIDAD (Factor puro: 0.0 a 1.0)
        factor_calidad = 0.0
        
        if produccion_bruta_total > 0:
            piezas_buenas = produccion_bruta_total - total_desperdiciado
            piezas_buenas_seguro = max(0, piezas_buenas) 
            factor_calidad = (piezas_buenas_seguro / produccion_bruta_total)
        
        return factor_calidad, {
            "produccion_bruta_total": produccion_bruta_total,
            "total_desperdiciado": total_desperdiciado,
        }
        
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)
            
        factor_calidad, data = self._calculate_factor_calidad(fecha_desde, fecha_hasta)
        
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "produccion_bruta_total": data['produccion_bruta_total'],
            "total_desperdiciado": data['total_desperdiciado'],
            "factor_calidad_oee": round(factor_calidad * 100.0, 2)
        }
        return Response(resultado)

# ====================================================================
# 2. FACTOR DE RENDIMIENTO
# ====================================================================

class ReporteFactorRendimientoOEE(APIView):
    """
    API para calcular el Factor de Rendimiento del OEE, usando el tiempo programado 
    como denominador y la tasa ideal (cant_por_hora) de ProductoLinea.
    """

    def _calculate_factor_rendimiento(self, fecha_desde, fecha_hasta):
        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        ots_completadas = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=rango_fecha_filtro,
            id_estado_orden_trabajo__descripcion='Completada'
        ).select_related('id_orden_produccion', 'id_linea_produccion')

        if not ots_completadas.exists():
            return 0.0, {}

        # --- A. CÁLCULO DEL DENOMINADOR: TIEMPO DE FUNCIONAMIENTO (PROGRAMADO) ---
        tiempo_programado_total_delta = ots_completadas.aggregate(
            total_delta=Coalesce(
                Sum(F('hora_fin_programada') - F('hora_inicio_programada')),
                Value(timedelta(seconds=0)),
                output_field=fields.DurationField()
            )
        )['total_delta']

        tiempo_funcionamiento_minutos = tiempo_programado_total_delta.total_seconds() / 60
        
        if tiempo_funcionamiento_minutos <= 0:
            return 0.0, {"tiempo_funcionamiento_minutos": 0.0, "produccion_bruta_total": 0.0}

        # --- B. CÁLCULO DEL NUMERADOR: TIEMPO DE PRODUCCIÓN IDEAL REQUERIDO ---
        
        # Subquery para obtener la tasa ideal (cant_por_hora)
        tasa_ideal_subquery = ProductoLinea.objects.filter(
            id_linea_produccion=OuterRef('id_linea_produccion'), 
            id_producto=OuterRef('id_orden_produccion__id_producto') 
        ).values('cant_por_hora')[:1] 

        ots_anotadas = ots_completadas.annotate(
            cant_por_hora_ideal=Subquery(tasa_ideal_subquery, output_field=fields.IntegerField())
        )
        
        ots_con_tiempo_ideal = ots_anotadas.annotate(
            tiempo_ideal_ot=Case(
                When(cant_por_hora_ideal__isnull=True, then=Value(0.0)),
                When(cant_por_hora_ideal__lte=0, then=Value(0.0)),
                default=ExpressionWrapper(
                    (F('produccion_bruta') / Cast('cant_por_hora_ideal', FloatField())) * 60,
                    output_field=FloatField()
                )
            )
        )

        agregacion_ideal = ots_con_tiempo_ideal.aggregate(
            produccion_ideal_requerida_minutos=Coalesce(Sum('tiempo_ideal_ot'), Value(0.0), output_field=FloatField()),
            produccion_bruta_total=Coalesce(Sum('produccion_bruta'), Value(0.0), output_field=FloatField())
        )
        
        produccion_ideal_requerida_minutos = agregacion_ideal['produccion_ideal_requerida_minutos']
        produccion_bruta_total = agregacion_ideal['produccion_bruta_total']


        # --- C. CÁLCULO DEL FACTOR RENDIMIENTO (Factor puro: 0.0 a 1.0) ---
        factor_rendimiento = 0.0
        if tiempo_funcionamiento_minutos > 0:
             factor_rendimiento = (produccion_ideal_requerida_minutos / tiempo_funcionamiento_minutos)
        
        return factor_rendimiento, {
            "produccion_bruta_total": produccion_bruta_total,
            "tiempo_funcionamiento_minutos": tiempo_funcionamiento_minutos,
            "tiempo_ideal_requerido_minutos": produccion_ideal_requerida_minutos
        }

    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)
            
        factor_rendimiento, data = self._calculate_factor_rendimiento(fecha_desde, fecha_hasta)
        
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "produccion_bruta_total": data.get("produccion_bruta_total", 0.0),
            "tiempo_funcionamiento_minutos": round(data.get("tiempo_funcionamiento_minutos", 0.0), 2),
            "tiempo_ideal_requerido_minutos": round(data.get("tiempo_ideal_requerido_minutos", 0.0), 2),
            "factor_rendimiento_oee": round(factor_rendimiento * 100.0, 2)
        }
        return Response(resultado)

# ====================================================================
# 3. FACTOR DE DISPONIBILIDAD AJUSTADA
# ====================================================================

class ReporteDisponibilidadAjustada(APIView):
    """
    API que calcula el indicador de Disponibilidad Ajustada (Eficacia Operativa).
    Utiliza el método original de agregación directa (Sum('pausas__duracion_minutos')).
    """
    
    def _calculate_disponibilidad_ajustada(self, fecha_desde, fecha_hasta):
        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # 1. Conjunto Base: OTs Completadas y con tiempos reales en el rango
        ots_base = OrdenDeTrabajo.objects.filter(
            id_estado_orden_trabajo__descripcion='Completada',
            hora_inicio_real__isnull=False,
            hora_fin_real__isnull=False,
            hora_inicio_programada__range=rango_fecha_filtro
        )
        
        # 2. Anotar el Tiempo de Carga Ajustado y el indicador de penalización
        ots_anotadas = ots_base.annotate(
            # 2.1. Tiempo de Carga Ajustado (Tiempo Transcurrido Bruto)
            tiempo_carga_ajustado_td=ExpressionWrapper(
                F('hora_fin_real') - F('hora_inicio_real'),
                output_field=fields.DurationField()
            ),
            
            # 2.2. Diferencia de Fechas (DurationField)
            retraso_fecha_td=ExpressionWrapper(
                F('hora_fin_real__date') - F('hora_fin_programada__date'),
                output_field=fields.DurationField()
            ),
            
        ).annotate(
            # Indicador de Tarde: Verificamos si la duración es mayor a 0 segundos
            termino_tarde=Case(
                When(retraso_fecha_td__gt=timedelta(seconds=0), then=Value(True)), 
                default=Value(False),
                output_field=fields.BooleanField()
            )
        )

        # 3. Agregación de Totales (Sumas)
        # 🚨 USANDO AGREGACIÓN DIRECTA: Sum('pausas__duracion_minutos')
        reporte_agregado = ots_anotadas.aggregate(
            # 3.1. Total de Pausas (Pérdidas por Paradas) en minutos
            total_perdida_pausas_minutos=Coalesce(
                Sum('pausas__duracion_minutos'), # ⬅️ USADO TAL CUAL ESTABA
                Value(0.0), # Usamos 0.0 para consistencia con FloatField
                output_field=FloatField()
            ),
            
            # 3.2. Suma del Tiempo de Carga Ajustado Total (Denominador Bruto) en segundos
            total_tiempo_carga_segundos=Coalesce(
                Sum(F('tiempo_carga_ajustado_td')),
                Value(timedelta(0)),
                output_field=fields.DurationField()
            ),
            
            # 3.3. TIEMPO PERDIDO POR DISCIPLINIDAD DE FECHA (Penalización)
            total_penalizado_tarde_segundos=Coalesce(
                Sum(
                    Case(
                        When(termino_tarde=True, then='tiempo_carga_ajustado_td'),
                        default=Value(timedelta(0)),
                        output_field=fields.DurationField()
                    )
                ),
                Value(timedelta(0)),
                output_field=fields.DurationField()
            )
        )

        # 4. Cálculo final y Conversión a Minutos
        total_tiempo_carga_segundos = reporte_agregado['total_tiempo_carga_segundos'].total_seconds()
        total_tiempo_carga_minutos = total_tiempo_carga_segundos / 60.0
        
        total_perdida_pausas = reporte_agregado['total_perdida_pausas_minutos']
        total_penalizado_tarde = reporte_agregado['total_penalizado_tarde_segundos'].total_seconds() / 60.0

        # Pérdidas Totales = Pausas + Penalización por Tarde
        perdidas_totales = total_perdida_pausas + total_penalizado_tarde

        # Tiempo Operación Neto = Tiempo Carga Bruto - Pérdidas Totales
        tiempo_operacion_neto = total_tiempo_carga_minutos - perdidas_totales
        
        # Tasa de Disponibilidad Ajustada (Factor puro: 0.0 a 1.0)
        disponibilidad_ajustada = 0.0
        if total_tiempo_carga_minutos > 0:
            # Aseguramos que el factor no sea negativo
            disponibilidad_ajustada = max(0, tiempo_operacion_neto) / total_tiempo_carga_minutos
            
        # Devolver el factor (0.0 a 1.0) y los datos clave
        return disponibilidad_ajustada, {
             "total_tiempo_carga_minutos": total_tiempo_carga_minutos,
             "total_perdida_pausas": total_perdida_pausas,
             "total_penalizado_tarde": total_penalizado_tarde
        }

    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)
            
        factor_disponibilidad, data = self._calculate_disponibilidad_ajustada(fecha_desde, fecha_hasta)
        
        # Formato de respuesta para el endpoint individual (como porcentaje)
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_tiempo_ejecucion_minutos": round(data['total_tiempo_carga_minutos'], 2),
            "total_tiempo_perdido_pausas_minutos": round(data['total_perdida_pausas'], 2),
            "total_penalizado_por_fecha_minutos": round(data['total_penalizado_tarde'], 2),
            "disponibilidad_ajustada_porcentaje": round(factor_disponibilidad * 100.0, 2)
        }
        return Response(resultado)

# ====================================================================
# 4. OEE GENERAL
# ====================================================================

class ReporteOEEGeneral(APIView):
    def get(self, request, *args, **kwargs):
        # Asumimos que parsear_fechas devuelve objetos datetime.
        fecha_desde_global, fecha_hasta_global = parsear_fechas(request)
        
        if fecha_desde_global is None or fecha_desde_global > fecha_hasta_global:
            # Si el rango es inválido, retornamos una lista vacía o un error claro.
            return Response({"error": "Rango de fechas inválido o nulo."}, status=400)

        resultados_mensuales = []
        
        # Preparamos las instancias de las vistas de factores (OPTIMAL)
        disponibilidad_view = ReporteDisponibilidadAjustada()
        rendimiento_view = ReporteFactorRendimientoOEE()
        calidad_view = ReporteFactorCalidadOEE()

        # Inicializar el bucle mensual
        fecha_actual_desde = fecha_desde_global
        
        # 1. Bucle principal para iterar mes a mes
        # Usamos el primer día del mes para la comparación (más robusto)
        while fecha_actual_desde.date() <= fecha_hasta_global.date():
            
            # 2. Calcular el primer día del próximo mes (para el avance y el límite)
            # El uso de relativedelta requiere la importación (python-dateutil)
            fecha_proximo_mes = fecha_actual_desde.replace(day=1) + relativedelta(months=1)
            
            # 3. Establecer el fin del periodo de cálculo: 
            # Es el final del mes, PERO sin exceder la fecha_hasta_global.
            fecha_actual_hasta = fecha_proximo_mes - timedelta(seconds=1)
            
            # 4. Ajustar el fin del periodo si excede la fecha de fin global
            if fecha_actual_hasta > fecha_hasta_global:
                fecha_actual_hasta = fecha_hasta_global

            # 5. Si la fecha_actual_desde es posterior a la fecha_actual_hasta ajustada,
            # (solo ocurre si la fecha_desde_global es, por ejemplo, el 31/01 y la fecha_hasta_global es el 01/02),
            # salimos del bucle. Esto ayuda a evitar cálculos con rango inverso.
            if fecha_actual_desde > fecha_actual_hasta:
                break

            # 6. Calcular los 3 factores para el PERIODO ACTUAL [fecha_actual_desde, fecha_actual_hasta]
            # NOTA: Los métodos internos deben devolver un float entre 0.0 y 1.0 (ej. 0.85)
            factor_disponibilidad, _ = disponibilidad_view._calculate_disponibilidad_ajustada(fecha_actual_desde, fecha_actual_hasta)
            factor_rendimiento, _ = rendimiento_view._calculate_factor_rendimiento(fecha_actual_desde, fecha_actual_hasta)
            factor_calidad, _ = calidad_view._calculate_factor_calidad(fecha_actual_desde, fecha_actual_hasta)

            # 7. CÁLCULO FINAL DEL OEE
            factor_oee = factor_disponibilidad * factor_rendimiento * factor_calidad
            
            # 8. Guardar el resultado del mes
            resultados_mensuales.append({
                # Usamos el primer día del mes para representar el período
                "periodo_inicio": fecha_actual_desde.strftime('%Y-%m-%d'),
                "periodo_fin": fecha_actual_hasta.strftime('%Y-%m-%d'),
                "disponibilidad": round(factor_disponibilidad * 100.0, 2),
                "rendimiento": round(factor_rendimiento * 100.0, 2),
                "calidad": round(factor_calidad * 100.0, 2),
                "oee_total": round(factor_oee * 100.0, 2),
            })
            
            # 9. Mover al inicio del próximo mes para la siguiente iteración
            fecha_actual_desde = fecha_proximo_mes

        return Response(resultados_mensuales)


# ====================================================================
# 1. INDICADORES DE VENTAS Y CANALES
# ====================================================================

class ReporteVolumenPorTipo(APIView):
    """ Calcula el volumen de ventas (conteo de órdenes) por canal (tipo_venta). """
    def get(self, request):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Fechas inválidas."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Agrupar por tipo de venta y contar órdenes
        resultados_agrupados = OrdenVenta.objects.filter(
            fecha__range=(fecha_desde, fecha_hasta)
        ).values('tipo_venta').annotate(
            conteo_ordenes=Sum(Value(1))
        )

        # 2. Calcular el total global para sacar porcentajes
        total_global = sum(item['conteo_ordenes'] for item in resultados_agrupados)
        
        # 3. Formatear
        reporte = []
        for item in resultados_agrupados:
            porcentaje = (item['conteo_ordenes'] / total_global) * 100 if total_global > 0 else 0.0
            reporte.append({
                "tipo_venta": item['tipo_venta'],
                "ordenes_contadas": item['conteo_ordenes'],
                "porcentaje": round(porcentaje, 2)
            })

        return Response(reporte)


class ReporteTiempoCicloVenta(APIView):
    """ Calcula el Tiempo de Ciclo de Venta (Lead Time) promedio para órdenes completadas. """
    def get(self, request):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Fechas inválidas."}, status=status.HTTP_400_BAD_REQUEST)
        
        # 1. Calcular el promedio de la duración (fecha_entrega - fecha)
        # Filtramos solo órdenes completadas que caen en el rango por fecha de creación
        tiempo_ciclo_agregado = OrdenVenta.objects.filter(
            fecha__range=(fecha_desde, fecha_hasta),
            fecha_entrega__isnull=False # Asegura que la orden esté completada
        ).aggregate(
            duracion_promedio=Avg(
                F('fecha_entrega') - F('fecha')
            )
        )

        duracion_delta = tiempo_ciclo_agregado.get('duracion_promedio')
        
        # 2. Formatear a un valor legible (Ej: días o segundos)
        promedio_dias = duracion_delta.total_seconds() / (60 * 60 * 24) if duracion_delta else 0.0

        reporte = {
            "tiempo_ciclo_promedio_dias": round(promedio_dias, 2),
            "total_ordenes_completadas": OrdenVenta.objects.filter(fecha__range=(fecha_desde, fecha_hasta), fecha_entrega__isnull=False).count()
        }
        return Response(reporte)


class ReporteCumplimientoFecha(APIView):
    """ Calcula la Tasa de Cumplimiento de Fecha Estimada (fecha_entrega <= fecha_estimada). """
    def get(self, request):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Fechas inválidas."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Filtrar solo órdenes con tiempos de cumplimiento relevantes
        ots_completadas = OrdenVenta.objects.filter(
            fecha__range=(fecha_desde, fecha_hasta),
            fecha_entrega__isnull=False,
            fecha_estimada__isnull=False
        )
        
        total_completadas = ots_completadas.count()

        if total_completadas == 0:
            return Response({"tasa_cumplimiento": 0.0, "total_ordenes_analizadas": 0})
        
        # 2. Contar órdenes que cumplieron la fecha (fecha_entrega <= fecha_estimada)
        cumplimiento_agregado = ots_completadas.aggregate(
            ordenes_cumplidas=Sum(
                Case(
                    # Nota: Usamos __date para comparar solo la parte de la fecha, ignorando la hora
                    When(fecha_entrega__date__lte=F('fecha_estimada'), then=Value(1)),
                    default=Value(0)
                )
            )
        )
        
        ordenes_cumplidas = cumplimiento_agregado['ordenes_cumplidas'] or 0
        tasa_cumplimiento = (ordenes_cumplidas / total_completadas) * 100.0

        reporte = {
            "tasa_cumplimiento": round(tasa_cumplimiento, 2),
            "ordenes_cumplidas": ordenes_cumplidas,
            "total_ordenes_analizadas": total_completadas
        }
        return Response(reporte)

# ====================================================================
# 2. INDICADORES FINANCIEROS Y TRANSACCIONALES
# ====================================================================

class ReporteTotalDineroVentas(APIView):
    """ Calcula la Suma Total de Dinero en Ventas. """
    def get(self, request):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Fechas inválidas."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Calcular la multiplicación de cantidad * precio (asumiendo que OrdenVenta tiene campo 'fecha')
        total_dinero = OrdenVentaProducto.objects.filter(
            id_orden_venta__fecha__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_ventas=Coalesce(
                Sum(F('cantidad') * F('id_producto__precio')), # Usamos F('id_producto__precio')
                Value(0.0),
                output_field=FloatField()
            )
        )['total_ventas']

        return Response({
            "total_dinero_ventas": round(total_dinero, 2)
        })


class ReporteValorPedidoPromedio(APIView):
    """ Calcula el Valor de Pedido Promedio (AOV). """
    def get(self, request):
        # 1. Reutilizamos el cálculo de Suma Total de Dinero en Ventas
        total_dinero_response = ReporteTotalDineroVentas().get(request).data
        total_dinero = total_dinero_response.get('total_dinero_ventas', 0.0)
        
        # 2. Contar el número total de órdenes
        fecha_desde, fecha_hasta = parsear_fechas(request)
        total_ordenes = OrdenVenta.objects.filter(fecha__range=(fecha_desde, fecha_hasta)).count()
        
        # 3. Calcular AOV
        aov = (total_dinero / total_ordenes) if total_ordenes > 0 else 0.0

        return Response({
            "valor_pedido_promedio": round(aov, 2),
            "total_ordenes": total_ordenes
        })


class ReporteProductosPorVenta(APIView):
    """ Calcula la Cantidad Promedio de Productos (unidades) por Venta. """
    def get(self, request):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Fechas inválidas."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Sumar todas las cantidades de productos vendidos
        total_unidades = OrdenVentaProducto.objects.filter(
            id_orden_venta__fecha__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total=Coalesce(Sum('cantidad'), Value(0))
        )['total']
        
        # 2. Contar el número total de órdenes
        total_ordenes = OrdenVenta.objects.filter(fecha__range=(fecha_desde, fecha_hasta)).count()

        # 3. Calcular promedio
        promedio = (total_unidades / total_ordenes) if total_ordenes > 0 else 0.0

        return Response({
            "unidades_promedio_por_venta": round(promedio, 2),
            "total_unidades_vendidas": total_unidades
        })

# ====================================================================
# 3. INDICADORES DE PRODUCTO
# ====================================================================

class ReporteDistribucionProductoPorTipo(APIView):
    """ Calcula la Distribución de Productos por Tipo en el catálogo. """
    def get(self, request):
        # 1. Agrupar por tipo de producto y contar
        resultados_agrupados = Producto.objects.values(
            'id_tipo_producto__descripcion' # Usamos el related name para obtener la descripción
        ).annotate(
            conteo=Sum(Value(1))
        ).order_by('id_tipo_producto__descripcion')

        # 2. Calcular el total global para sacar porcentajes
        total_global = Producto.objects.count()
        
        # 3. Formatear
        reporte = []
        for item in resultados_agrupados:
            porcentaje = (item['conteo'] / total_global) * 100 if total_global > 0 else 0.0
            reporte.append({
                "tipo_producto": item['id_tipo_producto__descripcion'],
                "conteo": item['conteo'],
                "porcentaje": round(porcentaje, 2)
            })

        return Response(reporte)