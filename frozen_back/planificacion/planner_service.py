import math
from collections import defaultdict
from django.utils import timezone
from django.db import transaction
# ❗️ Importar Count para chequear tareas restantes
from django.db.models import Q, Sum, Count 
from datetime import timedelta, date, datetime

from produccion.models import (
    OrdenProduccion,
    LineaProduccion,
    OrdenDeTrabajo,
    EstadoOrdenProduccion,
    EstadoOrdenTrabajo,
    CalendarioProduccion
)

from recetas.models import ProductoLinea
from ortools.sat.python import cp_model


HORIZONTE_MINUTOS = 16 * 60
SOLVER_MAX_SECONDS = 30
SOLVER_WORKERS = 8


def ejecutar_planificador(fecha_simulada: date):
    """
    NUEVA LÓGICA (Solver Táctico / Dispatcher):
    Lee las TAREAS del CalendarioProduccion para "mañana" y
    las optimiza para generar las OrdenesDeTrabajo (OTs).
    """

    dia_de_planificacion = fecha_simulada #+ timezone.timedelta(days=1)
    print(f"Iniciando Solver Táctico para {dia_de_planificacion}...")

    # ===================================================================
    # ✅ 1) SELECCIONAR TAREAS (CALENDARIO) PARA "MAÑANA"
    # ===================================================================
    
    # --- ❗️ INICIO DE CORRECCIÓN 1 ---
    # El Solver ahora busca OPs "Pendiente de inicio" (primer día)
    # O "En proceso" (días siguientes).
    estados_op_validos = ["Pendiente de inicio", "En proceso", "Finalizada"]
    
    tasks_today = list(
        CalendarioProduccion.objects.filter(
            fecha=dia_de_planificacion,
            id_orden_produccion__id_estado_orden_produccion__descripcion__in=estados_op_validos
        ).select_related(
            'id_orden_produccion__id_producto',
            'id_linea_produccion'
        ).order_by('id_orden_produccion__id_orden_produccion')
    )
    # --- ❗️ FIN DE CORRECCIÓN 1 ---

    if not tasks_today:
        print(f"✅ No hay líneas de calendario ({', '.join(estados_op_validos)}) para planificar en {dia_de_planificacion}.")
        return

    # ===================================================================
    # ✅ 2) OBTENER REGLAS Y LÍNEAS (Sin cambios)
    # ===================================================================
    lineas_activas = list(
        LineaProduccion.objects.filter(
            Q(id_estado_linea_produccion__descripcion="Disponible") |
            Q(id_estado_linea_produccion__descripcion="Ocupada")
        )
    )
    lineas_activas_ids = set(l.id_linea_produccion for l in lineas_activas)

    if not lineas_activas:
        print("❌ No hay líneas disponibles.")
        return

    productos_ids = list(set(task.id_orden_produccion.id_producto_id for task in tasks_today))
    lineas_ids = list(set(task.id_linea_produccion_id for task in tasks_today))

    reglas = ProductoLinea.objects.filter(
        id_producto_id__in=productos_ids,
        id_linea_produccion_id__in=lineas_ids
    ).values(
        "id_producto_id",
        "id_linea_produccion_id",
        "cant_por_hora",
        "cantidad_minima"
    )

    capacidad_lookup = {
        (r["id_producto_id"], r["id_linea_produccion_id"]): {
            "cant_por_hora": r["cant_por_hora"],
            "cantidad_minima": r["cantidad_minima"] or 0
        }
        for r in reglas
    }

    if not capacidad_lookup:
        print("❌ No hay reglas Producto ↔ Línea válidas. No se puede planificar.")
        return

    # ===================================================================
    # ✅ 3) CREAR MODELO (Basado en TAREAS, no en OPs) (Sin cambios)
    # ===================================================================
    model = cp_model.CpModel()
    intervals_por_linea = defaultdict(list)
    todas_tandas = []
    all_end_vars = []

    print("✅ Generando tandas según CalendarioProduccion...")
    
    for cal_task in tasks_today:
        op = cal_task.id_orden_produccion
        linea = cal_task.id_linea_produccion
        producto_id = op.id_producto_id
        
        total_task_qty = int(cal_task.cantidad_a_producir)
        max_horas_tarea = int(cal_task.horas_reservadas)
        max_minutos_tarea = max_horas_tarea * 60

        # --- Validaciones ---
        if linea.id_linea_produccion not in lineas_activas_ids:
            print(f"❌ Línea {linea.id_linea_produccion} no está disponible. Omitiendo tarea de OP {op.id_orden_produccion}.")
            continue

        if (producto_id, linea.id_linea_produccion) not in capacidad_lookup:
            print(f"❌ No hay regla para OP {op.id_orden_produccion} en Línea {linea.id_linea_produccion}. Omitiendo.")
            continue
            
        regla = capacidad_lookup[(producto_id, linea.id_linea_produccion)]
        tamano_tanda = regla["cant_por_hora"]
        minimo = regla["cantidad_minima"] or 0
        
        if tamano_tanda <= 0:
            print(f"⚠️ TAMAÑO TANDA 0: OP {op.id_orden_produccion} en línea {linea.id_linea_produccion}")
            continue
        
        max_tandas = math.ceil(total_task_qty / tamano_tanda)
        
        if max_tandas == 0:
            continue

        task_tandas = [] 

        for t in range(max_tandas):
            if t == max_tandas - 1:
                sobra = total_task_qty - (tamano_tanda * (max_tandas - 1))
                if sobra < minimo:
                    print(f"⚠️ Tanda final de Tarea {cal_task.id} (OP {op.id}) en línea {linea.id_linea_produccion} ({sobra}u) < mínimo ({minimo}). No se generará.")
                    continue
                tamano_real = sobra
            else:
                tamano_real = tamano_tanda
            
            duracion_real = math.ceil(60 * (tamano_real / tamano_tanda))
            if duracion_real <= 0:
                continue
                
            lit = model.NewBoolVar(
                f"cal{cal_task.id}_t{t}"
            )
            start = model.NewIntVar(0, HORIZONTE_MINUTOS, "")
            end = model.NewIntVar(0, HORIZONTE_MINUTOS, "")
            interval = model.NewOptionalIntervalVar(start, duracion_real, end, lit, "")
            
            tanda_info = {
                "literal": lit,
                "op": op,
                "linea": linea,
                "tamano": tamano_real,
                "start": start,
                "end": end,
                "duracion": duracion_real,
                "cal_task_id": cal_task.id
            }
            
            todas_tandas.append(tanda_info)
            task_tandas.append(tanda_info)
            intervals_por_linea[linea.id_linea_produccion].append(interval)
            all_end_vars.append(end)

        model.Add(
            sum(
                tanda["literal"] * tanda["tamano"]
                for tanda in task_tandas
            ) == total_task_qty
        )
        
        model.Add(
            sum(
                tanda["literal"] * tanda["duracion"]
                for tanda in task_tandas
            ) <= max_minutos_tarea
        )

    # ... (Resto del setup del modelo: NoOverlap, Makespan, Maximize) ...
    for linea_id, intervals in intervals_por_linea.items():
        model.AddNoOverlap(intervals)
    makespan = model.NewIntVar(0, HORIZONTE_MINUTOS, "makespan")
    model.AddMaxEquality(makespan, all_end_vars)
    produccion_total = model.NewIntVar(0, sum(t.cantidad_a_producir for t in tasks_today), "produccion_total")
    model.Add(
        produccion_total == sum(
            tanda["literal"] * tanda["tamano"]
            for tanda in todas_tandas
        )
    )
    model.Maximize(produccion_total)
    
    # ===================================================================
    # ✅ 4) EJECUTAR SOLVER Y GUARDAR
    # ===================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_MAX_SECONDS
    solver.parameters.num_search_workers = SOLVER_WORKERS

    status = solver.Solve(model)

    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        print(f"❌ No se pudo generar una planificación para {dia_de_planificacion}.")
        
        estado_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera")
        op_ids = set(t.id_orden_produccion_id for t in tasks_today)
        OrdenProduccion.objects.filter(id_orden_produccion__in=op_ids).update(id_estado_orden_produccion=estado_en_espera)
        
        CalendarioProduccion.objects.filter(
            id_orden_produccion_id__in=op_ids,
            fecha=dia_de_planificacion # Borra solo las de hoy, para que MRP las reprograme
        ).delete()
        print(f"Ops {list(op_ids)} devueltas a 'En espera'. Reservas de calendario de HOY limpiadas.")
        return

    # ✅ Guardar resultados
    estado_ot = EstadoOrdenTrabajo.objects.get(descripcion="Pendiente")
    estado_op_planificada = EstadoOrdenProduccion.objects.get(descripcion="Planificada")
    estado_op_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera")
    estado_op_en_proceso = EstadoOrdenProduccion.objects.get(descripcion="En proceso")

    hora_base_dt = timezone.make_aware(datetime.combine(dia_de_planificacion, datetime.min.time()))

    ots_creadas = []
    ops_planificadas_exitosamente = set() # ID de OPs con OTs creadas
    cal_tasks_exitosas_ids = set() # ID de Tareas del Calendario completadas

    for tanda in todas_tandas:
        if solver.Value(tanda["literal"]):
            ini = solver.Value(tanda["start"])
            fin = solver.Value(tanda["end"])
            ots_creadas.append(
                OrdenDeTrabajo(
                    id_orden_produccion=tanda["op"],
                    id_linea_produccion=tanda["linea"],
                    cantidad_programada=tanda["tamano"],
                    hora_inicio_programada=hora_base_dt + timezone.timedelta(minutes=ini),
                    hora_fin_programada=hora_base_dt + timezone.timedelta(minutes=fin),
                    id_estado_orden_trabajo=estado_ot
                )
            )
            ops_planificadas_exitosamente.add(tanda["op"].id_orden_produccion)
            cal_tasks_exitosas_ids.add(tanda["cal_task_id"])

    # --- ❗️ INICIO DE CORRECCIÓN 2 ---
    # Lógica de actualización de estado
    
    ops_originales_ids = set(task.id_orden_produccion_id for task in tasks_today)
    ops_fallidas_ids = ops_originales_ids - ops_planificadas_exitosamente
    cal_tasks_originales_ids = set(task.id for task in tasks_today)
    cal_tasks_fallidas_ids = cal_tasks_originales_ids - cal_tasks_exitosas_ids


    with transaction.atomic():
        # 1. Crear las OTs
        OrdenDeTrabajo.objects.bulk_create(ots_creadas)
        print(f"✅ {len(ots_creadas)} OTs creadas exitosamente para {dia_de_planificacion}.")

        # 2. Limpiar TAREAS de Calendario exitosas
        if cal_tasks_exitosas_ids:
            reservas_blandas_borradas = CalendarioProduccion.objects.filter(
                id__in=cal_tasks_exitosas_ids
            ).delete()
            print(f"🧹 Limpiadas {reservas_blandas_borradas[0]} reservas de calendario EXITOSAS.")
        
        # 3. Actualizar estado de OPs exitosas
        if ops_planificadas_exitosamente:
            
            # ❗️ Primero, movemos todas las OPs "Pendiente de inicio" a "En proceso"
            ops_actualizadas_a_proceso = OrdenProduccion.objects.filter(
                id_orden_produccion__in=ops_planificadas_exitosamente,
                id_estado_orden_produccion__descripcion="Pendiente de inicio" 
            ).update(id_estado_orden_produccion=estado_op_en_proceso)
            
            if ops_actualizadas_a_proceso > 0:
                print(f"✅ {ops_actualizadas_a_proceso} OPs movidas de 'Pendiente de inicio' a 'En proceso'.")

            # ❗️ Segundo, buscamos OPs que (después de borrar) ya no tengan tareas futuras
            ops_para_chequear_finalizacion = ops_planificadas_exitosamente
            
            ops_sin_tareas_futuras = OrdenProduccion.objects.filter(
                id_orden_produccion__in=ops_para_chequear_finalizacion
            ).annotate(
                # Contamos cuántas reservas de calendario le quedan (en cualquier fecha)
                tareas_calendario_restantes=Count('reservas_calendario') 
            ).filter(
                tareas_calendario_restantes=0 # Si le quedan 0
            )

            if ops_sin_tareas_futuras.exists():
                ids_ops_finalizadas = list(ops_sin_tareas_futuras.values_list('id_orden_produccion', flat=True))
                print(f"🎉 OPs {ids_ops_finalizadas} han completado su última tarea de calendario.")
                
                # Las movemos a "Planificada" (listas para cierre por el supervisor)
                ops_sin_tareas_futuras.update(id_estado_orden_produccion=estado_op_planificada)

        # 4. Gestionar Tareas y OPs que FALLARON hoy
        if cal_tasks_fallidas_ids:
            print(f"⚠️ {len(cal_tasks_fallidas_ids)} TAREAS de Calendario no pudieron ser planificadas hoy por el solver.")
            
            # Devolvemos las OPs fallidas a "En espera" para que el MRP las reprograme
            OrdenProduccion.objects.filter(
                id_orden_produccion__in=ops_fallidas_ids
            ).update(
                id_estado_orden_produccion=estado_op_en_espera
            )
            
            # Borramos TODAS las reservas de calendario de las OPs fallidas
            # (para que el MRP pueda replanificar desde cero)
            reservas_fallidas_borradas = CalendarioProduccion.objects.filter(
                id_orden_produccion_id__in=ops_fallidas_ids,
            ).delete()
            print(f"Devueltas {len(ops_fallidas_ids)} OPs a 'En espera'. Limpiadas {reservas_fallidas_borradas[0]} reservas de calendario (TODAS) de esas OPs.")
    # --- ❗️ FIN DE CORRECCIÓN 2 ---


def replanificar_produccion(fecha_objetivo=None):
    """
    Replanifica las órdenes de producción para una fecha determinada.
    MODIFICADO: Ahora solo limpia y devuelve a "En espera" para que el MRP
    se encargue de la reprogramación completa.
    """
    if fecha_objetivo is None:
        fecha_objetivo = timezone.localdate() + timezone.timedelta(days=1)

    print(f"🔄 Replanificando producción para: {fecha_objetivo}")

    # 1. Buscar OPs que tenían OTs o Calendario en esa fecha
    op_ids_calendario = set(CalendarioProduccion.objects.filter(
        fecha=fecha_objetivo
    ).values_list('id_orden_produccion_id', flat=True))
    
    op_ids_ots = set(OrdenDeTrabajo.objects.filter(
        hora_inicio_programada__date=fecha_objetivo
    ).values_list('id_orden_produccion_id', flat=True))
    
    op_ids_a_replanificar = op_ids_calendario.union(op_ids_ots)

    if not op_ids_a_replanificar:
        print("✅ No hay órdenes para replanificar en esa fecha.")
        return

    print(f"Se replanificarán {len(op_ids_a_replanificar)} OPs: {list(op_ids_a_replanificar)}")

    # 2. BORRAR OTs futuras no iniciadas
    estados_replanificables = EstadoOrdenTrabajo.objects.filter(
        descripcion__in=["Pendiente", "Planificada"]
    )
    ots_borradas = OrdenDeTrabajo.objects.filter(
        id_orden_produccion_id__in=op_ids_a_replanificar,
        id_estado_orden_trabajo__in=estados_replanificables,
        hora_inicio_programada__gte=timezone.now() # Solo futuras
    ).delete()
    print(f"🗑️ Eliminadas {ots_borradas[0]} OTs no iniciadas.")

    # 3. BORRAR TODAS las reservas de Calendario de esas OPs
    cal_borradas = CalendarioProduccion.objects.filter(
        id_orden_produccion_id__in=op_ids_a_replanificar
    ).delete()
    print(f"🗑️ Eliminadas {cal_borradas[0]} reservas de calendario (TODAS) de esas OPs.")

    # 4. Devolver OPs a estado "En espera"
    estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion="En espera")
    ops_actualizadas = OrdenProduccion.objects.filter(
        id_orden_produccion__in=op_ids_a_replanificar
    ).update(id_estado_orden_produccion=estado_pendiente)

    print(f"🔁 {ops_actualizadas} OPs marcadas como 'En espera' para que el MRP las reprograme.")
    print("✅ Replanificación (limpieza) completada. El próximo MRP se encargará.")