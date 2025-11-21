# Asumo que OrdenProduccion tiene el campo 'cantidad_producida' (entregada, o ya consumida por OTs terminadas)
from datetime import date
from django.db import transaction
from datetime import timedelta, datetime
from django.db.models import F, Sum, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
import math
from ventas.models import OrdenVenta, EstadoVenta
from recetas.models import ProductoLinea
from produccion.models import EstadoOrdenProduccion, OrdenProduccion, CalendarioProduccion, OrdenProduccionPegging, EstadoOrdenTrabajo
# Constantes
HORAS_LABORABLES_POR_DIA = 16
DIAS_BUFFER_ENTREGA_PT = 1  # Días de buffer entre fin de producción y entrega al cliente



@transaction.atomic
def replanificar_ops_por_capacidad(
    fecha_simulada: date, 
    productos_a_replanificar_ids: list[int] = None, 
    dias_minimo_a_replanificar: int = 2
):
    """
    Replanifica OPs activas (En espera, Pendiente de inicio, Planificada)
    que tienen reservas en el calendario a partir de pasado mañana,
    ajustando las horas y fechas para la cantidad pendiente de producir.
    """
    
    hoy = fecha_simulada
    # Fecha mínima: pasado mañana (o el valor de dias_minimo_a_replanificar)
    fecha_minima_replanificacion = hoy + timedelta(days=dias_minimo_a_replanificar) 
    
    print(f"--- INICIANDO REPLANIFICACIÓN POR CAPACIDAD ({hoy}) ---")
    print(f"--- Foco: OPs con reservas a partir de: {fecha_minima_replanificacion} ---")

    # 1. Obtener Estados Necesarios
    try:
        estado_op_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera")
        estado_op_pendiente_inicio = EstadoOrdenProduccion.objects.get(descripcion="Pendiente de inicio")
        estado_op_planificada = EstadoOrdenProduccion.objects.get(descripcion="Planificada") 
        estado_op_en_proceso = EstadoOrdenProduccion.objects.get(descripcion="En proceso")
        estado_ov_en_preparacion = EstadoVenta.objects.get(descripcion="En Preparación")
        # 🚨 Nuevo: Estado de OT finalizada para calcular lo ya producido
        estado_ot_finalizada = EstadoOrdenTrabajo.objects.get(descripcion__iexact="Completada") 
        estado_ot_pendiente = EstadoOrdenTrabajo.objects.get(descripcion__iexact="Pendiente")
        estado_ot_en_proceso = EstadoOrdenTrabajo.objects.get(descripcion__iexact="En progreso")
        # Ajusta "Completada" o "Finalizada" según tu BD
    except Exception as e:
        print(f"¡ERROR! No se pudieron obtener estados base: {e}")
        raise 
        
    estados_activos_para_replanificar = [
        estado_op_en_espera, 
        estado_op_pendiente_inicio, 
        estado_op_planificada,
        estado_op_en_proceso
    ]

    estados_ot_consumidos = [
        estado_ot_pendiente, 
        estado_ot_en_proceso, 
        estado_ot_finalizada
    ]
    
    # 2. Filtrar OPs Elegibles y Calcular Cantidad Pendiente
    ops_elegibles_query = OrdenProduccion.objects.filter(
        # Filtro A: Estado Activo (Incluye 'Planificada')
        id_estado_orden_produccion__in=estados_activos_para_replanificar,
        
        # 🚨 FILTRO B CORREGIDO: EXISTENCIA DE RESERVAS FUTURAS
        # Incluye OPs con fecha de inicio pasada que aún tienen trabajo pendiente.
        reservas_calendario__fecha__gte=fecha_minima_replanificacion 
        
    ).annotate(
        # 🚨 CÁLCULO CORREGIDO: Sumar la producción de OTs Finalizadas
        # Se asume que el campo en OrdenDeTrabajo es 'cantidad_producida_reportada' o similar.
        # Si tu modelo de OT solo tiene 'cantidad_programada', ajusta el campo.
        cantidad_producida_real=Coalesce(
            Sum(
                # Usamos 'cantidad_programada' porque es la cantidad que la OT "consumió" de la OP
                'ordenes_de_trabajo__cantidad_programada', 
                filter=Q(ordenes_de_trabajo__id_estado_orden_trabajo__in=estados_ot_consumidos)
            ), 
            0
        ), 
        # Calcular la cantidad que queda por planificar/producir
        cantidad_pendiente=F('cantidad') - F('cantidad_producida_real')
    ).filter(
        # Filtro C: Solo si aún les queda trabajo por hacer
        cantidad_pendiente__gt=0 
    ).select_related('id_producto').order_by('fecha_planificada').distinct()

    if productos_a_replanificar_ids:
        ops_elegibles_query = ops_elegibles_query.filter(id_producto__in=productos_a_replanificar_ids)
        
    ops_a_replanificar = list(ops_elegibles_query)
    
    print(f"   > Encontradas {len(ops_a_replanificar)} OPs elegibles para replanificar.")
    
    for op in ops_a_replanificar:
        
        cantidad_a_producir_restante = op.cantidad_pendiente
        producto = op.id_producto
        
        # 3.1 Recalcular Horas Necesarias con la Capacidad ACTUAL (para la cantidad restante)
        capacidades_linea = ProductoLinea.objects.filter(id_producto=producto)
        cant_total_por_hora = capacidades_linea.aggregate(total=Sum('cant_por_hora'))['total'] or 0
        
        if cant_total_por_hora <= 0:
            print(f"     !ERROR: Capacidad 0/hr para {producto.nombre}. No se puede replanificar.")
            continue
            
        horas_necesarias_float = float(cantidad_a_producir_restante) / float(cant_total_por_hora)
        horas_necesarias_totales = math.ceil(horas_necesarias_float)

        print(f"\n   --- Replanificando OP {op.id_orden_produccion} ({producto.nombre}).")
        print(f"     > Cantidad restante: {cantidad_a_producir_restante} u. Nuevas horas requeridas: {horas_necesarias_totales} hs.")

        # 4. Limpieza: Borrar todas las reservas de calendario VIEJAS (futuras)
        CalendarioProduccion.objects.filter(id_orden_produccion=op).delete()
        print(f"     > Eliminadas reservas de calendario previas (futuras).")
        
        # 5. Determinar Fecha de Inicio Mínima (punto de partida)
        # Empezamos a buscar hueco desde la fecha de inicio original o pasado mañana, lo que sea posterior.
        fecha_inicio_minima_real = max(
            op.fecha_planificada.date(), 
            fecha_minima_replanificacion
        )
        
        # 6. Walk the Calendar (Buscar nuevo hueco)
        cantidad_pendiente_op = cantidad_a_producir_restante
        horas_pendientes = horas_necesarias_totales 
        fecha_a_buscar = fecha_inicio_minima_real
        
        while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1) 

        fecha_inicio_real_asignada = None
        ultimo_dia_trabajado = None
        reservas_a_crear_bulk = []
        
        # --- INICIO LÓGICA DE CALENDAR WALK ---
        while horas_pendientes > 0 and cantidad_pendiente_op > 0:
            horas_libres_cuello_botella = HORAS_LABORABLES_POR_DIA
            lineas_ids_producto = [c.id_linea_produccion_id for c in capacidades_linea]
            
            # Carga existente de OPs activas
            carga_existente = CalendarioProduccion.objects.filter(
                id_linea_produccion_id__in=lineas_ids_producto,
                fecha=fecha_a_buscar,
                id_orden_produccion__id_estado_orden_produccion__in=estados_activos_para_replanificar
            ).values('id_linea_produccion_id').annotate(
                total_reservado=Sum('horas_reservadas')
            ).values('id_linea_produccion_id', 'total_reservado')
            
            carga_por_linea = {c['id_linea_produccion_id']: float(c['total_reservado']) for c in carga_existente}

            for linea_id in lineas_ids_producto:
                carga_dia = carga_por_linea.get(linea_id, 0.0)
                horas_libres_linea = max(0, HORAS_LABORABLES_POR_DIA - carga_dia)
                horas_libres_cuello_botella = min(horas_libres_cuello_botella, horas_libres_linea)

            horas_libres_enteras = math.floor(horas_libres_cuello_botella)

            if horas_libres_enteras <= 0:
                fecha_a_buscar += timedelta(days=1)
                while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1)
                continue
                    
            horas_a_reservar_hoy = min(horas_pendientes, horas_libres_enteras) 
            se_reservo_tiempo_en_fecha = False

            for cap_linea in capacidades_linea:
                cantidad_calculada_linea = round(float(horas_a_reservar_hoy) * float(cap_linea.cant_por_hora))
                cantidad_real_linea = min(cantidad_pendiente_op, cantidad_calculada_linea)

                if horas_a_reservar_hoy > 0 and cantidad_real_linea > 0:
                    se_reservo_tiempo_en_fecha = True 
                    
                    reservas_a_crear_bulk.append(
                        CalendarioProduccion(
                            id_orden_produccion=op, 
                            id_linea_produccion=cap_linea.id_linea_produccion,
                            fecha=fecha_a_buscar,
                            horas_reservadas=horas_a_reservar_hoy,
                            cantidad_a_producir=cantidad_real_linea
                        )
                    )
                    cantidad_pendiente_op -= cantidad_real_linea
                    
                    if cantidad_pendiente_op <= 0: break 
            
            if se_reservo_tiempo_en_fecha:
                horas_pendientes -= horas_a_reservar_hoy 
                ultimo_dia_trabajado = fecha_a_buscar
                if fecha_inicio_real_asignada is None:
                    fecha_inicio_real_asignada = fecha_a_buscar
            
            if cantidad_pendiente_op <= 0:
                horas_pendientes = 0 
                break

            fecha_a_buscar += timedelta(days=1)
            while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1)
            
            if cantidad_pendiente_op > 0:
                # Recalcular horas pendientes en base a la cantidad restante
                horas_necesarias_float_nueva = float(cantidad_pendiente_op) / float(cant_total_por_hora)
                horas_pendientes = math.ceil(horas_necesarias_float_nueva) 
        # --- FIN LÓGICA DE CALENDAR WALK ---

        # 7. Guardar OP y Calendario Nuevos
        if fecha_inicio_real_asignada is None:
            fecha_inicio_real_asignada = fecha_inicio_minima_real

        fecha_fin_real_asignada = ultimo_dia_trabajado if ultimo_dia_trabajado else fecha_inicio_real_asignada
        while fecha_fin_real_asignada.weekday() >= 5:
             fecha_fin_real_asignada -= timedelta(days=1)
        if fecha_fin_real_asignada < fecha_inicio_real_asignada:
            fecha_fin_real_asignada = fecha_inicio_real_asignada

        op.fecha_planificada = timezone.make_aware(datetime.combine(fecha_inicio_real_asignada, datetime.min.time()))
        op.fecha_fin_planificada = fecha_fin_real_asignada
        # No cambiamos el estado aquí, se mantiene 'Planificada', 'En espera' o 'Pendiente de inicio'
        op.save(update_fields=['fecha_planificada', 'fecha_fin_planificada'])
        
        CalendarioProduccion.objects.bulk_create(reservas_a_crear_bulk)
        
        print(f"     ✅ OP {op.id_orden_produccion} REPLANIFICADA. Nuevo rango: {op.fecha_planificada.date()} a {op.fecha_fin_planificada}.")

        # 8. Revisar y Desplazar OVs Vinculadas
        peggings = OrdenProduccionPegging.objects.filter(id_orden_produccion=op).select_related('id_orden_venta_producto__id_orden_venta')
        
        for peg in peggings:
            ov = peg.id_orden_venta_producto.id_orden_venta
            dias_totales_margen = DIAS_BUFFER_ENTREGA_PT + 1
            nueva_fecha_entrega_sugerida_date = op.fecha_fin_planificada + timedelta(days=dias_totales_margen)
            
            while nueva_fecha_entrega_sugerida_date.weekday() >= 5:
                 nueva_fecha_entrega_sugerida_date += timedelta(days=1) 

            if nueva_fecha_entrega_sugerida_date > ov.fecha_entrega.date():
                print(f"     🚨 ¡ALERTA! OV {ov.id_orden_venta} desplazada a {nueva_fecha_entrega_sugerida_date}.")
                ov.fecha_entrega = nueva_fecha_entrega_sugerida_date
                ov.id_estado_venta = estado_ov_en_preparacion 
                ov.save(update_fields=['fecha_entrega', 'id_estado_venta'])

    print("\n--- REPLANIFICACIÓN POR CAPACIDAD FINALIZADA ---")
    return True