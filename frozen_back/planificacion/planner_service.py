import math
from collections import defaultdict
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from datetime import timedelta, date, datetime

from produccion.models import (
    OrdenProduccion,
    LineaProduccion,
    OrdenDeTrabajo,
    EstadoOrdenProduccion,
    EstadoOrdenTrabajo,
    CalendarioProduccion  # ❗️ IMPORTAR EL NUEVO MODELO
)

from recetas.models import ProductoLinea
from ortools.sat.python import cp_model


HORIZONTE_MINUTOS = 16 * 60 # ❗️ AJUSTADO A 16 HORAS (16*60 = 960 minutos)
SOLVER_MAX_SECONDS = 30
SOLVER_WORKERS = 8


def ejecutar_planificador(fecha_simulada: date):

    # ❗️ Usar la fecha simulada para determinar "mañana"
    dia_de_planificacion = fecha_simulada + timezone.timedelta(days=1)
    # mañana = timezone.localdate() + timezone.timedelta(days=1) # Versión antigua

    # ✅ 1) Seleccionar solo OP para "mañana" (el día de planificación)
    # ❗️ AÑADIDO: order_by para priorizar (opcional)
    print(f"Iniciando Solver Táctico para {dia_de_planificacion}...")
    
    ordenes = list(
        OrdenProduccion.objects.filter(
            id_estado_orden_produccion__descripcion="Pendiente de inicio",
            fecha_planificada=dia_de_planificacion # <-- Esto ahora es la fecha REAL
        ).select_related("id_producto").order_by('id_orden_produccion') # o por prioridad
    )

    # ✅ 2) Seleccionar líneas activas
    lineas = list(
        LineaProduccion.objects.filter(
            Q(id_estado_linea_produccion__descripcion="Disponible") |
            Q(id_estado_linea_produccion__descripcion="Ocupada")
        )
    )

    if not ordenes:
        # ❗️ Ajustado el log para usar la variable correcta
        print(f"✅ No hay OP 'Pendiente de inicio' para planificar en {dia_de_planificacion}.")
        return

    if not lineas:
        print("❌ No hay líneas disponibles.")
        return

    # ... (Tu código de Cargar reglas, lookup, etc. no cambia) ...
    # ✅ 3) Cargar reglas producto ↔ línea
    productos_ids = [op.id_producto_id for op in ordenes]
    lineas_ids = [l.id_linea_produccion for l in lineas]
 
    reglas = ProductoLinea.objects.filter(
     id_producto_id__in=productos_ids,
     id_linea_produccion_id__in=lineas_ids
    ).values(
        "id_producto_id",
        "id_linea_produccion_id",
        "cant_por_hora",
        "cantidad_minima"
    )
 
    # ✅ Diccionario para lookup rápido
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
 
    # ✅ Lista final de líneas realmente aptas
    lineas_validas = [
        l for l in lineas
        if any((op.id_producto_id, l.id_linea_produccion) in capacidad_lookup
                for op in ordenes)
    ]
 
    if not lineas_validas:
        print("❌ No hay líneas capaces de producir los productos requeridos.")
        return

    # ✅ 4) Crear modelo
    model = cp_model.CpModel()
    intervals_por_linea = defaultdict(list)
    todas_tandas = []
    all_end_vars = []

    print("✅ Generando tandas según ProductoLinea...")

    # ... (Tu código de generación de tandas del Solver no cambia) ...
    for op in ordenes:
        total = int(op.cantidad)
        producto_id = op.id_producto_id
 
        # ✅ Solo líneas que aceptan este producto
        lineas_para_producto = [
            l for l in lineas_validas
            if (producto_id, l.id_linea_produccion) in capacidad_lookup
        ]
 
        if not lineas_para_producto:
            print(f"❌ El producto {op.id_producto_id} no puede producirse en ninguna línea.")
            continue
 
        for linea in lineas_para_producto:
 
            regla = capacidad_lookup[(producto_id, linea.id_linea_produccion)]
            tamano_tanda = regla["cant_por_hora"]
            minimo = regla["cantidad_minima"] or 0
 
            duracion_tanda = 60  # cada tanda dura 1 hora
            
            if tamano_tanda <= 0:
                print(f"⚠️ TAMAÑO TANDA 0: OP {op.id_orden_produccion} en línea {linea.id_linea_produccion}")
                continue
 
            max_tandas = math.ceil(total / tamano_tanda)
 
            for t in range(max_tandas):
 
                # Última tanda → puede ser parcial
                if t == max_tandas - 1:
                    sobra = total - (tamano_tanda * (max_tandas - 1))
 
                    # ❗ Si la tanda final es menor al mínimo, NO se produce
                    if sobra < minimo:
                        print(
                            f"⚠️ Tanda final de OP {op.id_orden_produccion} en línea {linea.id_linea_produccion} "
                            f"({sobra} unidades) menor al mínimo permitido ({minimo}). No se generará."
                        )
                        continue
 
                    tamano_real = sobra
                else:
                    tamano_real = tamano_tanda
 
                duracion_real = math.ceil(60 * (tamano_real / tamano_tanda))
                
                # ❗️ Control para evitar duraciones 0
                if duracion_real <= 0:
                    print(f"⚠️ DURACION 0: OP {op.id_orden_produccion} Tanda {t} / {tamano_real}u")
                    continue
 
                # Crear variables del solver
                lit = model.NewBoolVar(
                    f"op{op.id_orden_produccion}_l{linea.id_linea_produccion}_t{t}"
                )
                start = model.NewIntVar(0, HORIZONTE_MINUTOS, "")
                end = model.NewIntVar(0, HORIZONTE_MINUTOS, "")
                interval = model.NewOptionalIntervalVar(start, duracion_real, end, lit, "")
 
                todas_tandas.append({
                    "literal": lit,
                    "op": op,
                    "linea": linea,
                    "tamano": tamano_real,
                    "start": start,
                    "end": end
                })
 
                intervals_por_linea[linea.id_linea_produccion].append(interval)
                all_end_vars.append(end)
                
        # ✅ Cobertura sin obligar a producir cantidades menores al mínimo
        model.Add(
            sum(
                tanda["literal"] * tanda["tamano"]
                for tanda in todas_tandas
                if tanda["op"] == op
            ) <= total
        )
 
    # ✅ NoOverlap por línea
    for linea_id, intervals in intervals_por_linea.items():
        model.AddNoOverlap(intervals)
 
    # ✅ Minimizar makespan
    makespan = model.NewIntVar(0, HORIZONTE_MINUTOS, "makespan")
    model.AddMaxEquality(makespan, all_end_vars)
 
    # Variable que representa la producción total planificada
    produccion_total = model.NewIntVar(0, sum(op.cantidad for op in ordenes), "produccion_total")
 
    model.Add(
        produccion_total == sum(
            tanda["literal"] * tanda["tamano"]
            for tanda in todas_tandas
        )
    )
 
    model.Maximize(produccion_total)

    # ✅ Ejecutar solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_MAX_SECONDS
    solver.parameters.num_search_workers = SOLVER_WORKERS

    status = solver.Solve(model)

    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        print(f"❌ No se pudo generar una planificación para {dia_de_planificacion}.")
        # ❗️ Devolvemos TODAS las OPs de hoy a "En espera" para que se replanifiquen
        estado_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera")
        op_ids = [op.id_orden_produccion for op in ordenes]
        OrdenProduccion.objects.filter(id_orden_produccion__in=op_ids).update(id_estado_orden_produccion=estado_en_espera)
        
        # ❗️ Y limpiamos sus reservas de calendario para que el MRP pueda reasignar
        CalendarioProduccion.objects.filter(
            id_orden_produccion_id__in=op_ids,
            fecha=dia_de_planificacion
        ).delete()
        print(f"Ops {op_ids} devueltas a 'En espera'. Reservas de calendario limpiadas.")
        return

    # ✅ Guardar resultados
    estado_ot = EstadoOrdenTrabajo.objects.get(descripcion="Pendiente")
    estado_op_planificada = EstadoOrdenProduccion.objects.get(descripcion="Planificada")
    estado_op_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera") # Para OPs fallidas

    # ❗️ Usar el 'dia_de_planificacion' como base (ya es un objeto date)
    # ❗️ Necesitamos convertirlo a datetime para sumar minutos
    hora_base_dt = timezone.make_aware(datetime.combine(dia_de_planificacion, datetime.min.time()))

    ots_creadas = []
    ops_planificadas_exitosamente = set() # ID de OPs con OTs creadas

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

    # --- ❗️ LÓGICA DE ACTUALIZACIÓN Y LIMPIEZA ---
    
    # 1. Identificar OPs originales vs. OPs fallidas
    ops_originales_ids = set(op.id_orden_produccion for op in ordenes)
    ops_fallidas_ids = ops_originales_ids - ops_planificadas_exitosamente

    with transaction.atomic():
        # 2. Crear las OTs (Reservas "Duras")
        OrdenDeTrabajo.objects.bulk_create(ots_creadas)
        print(f"✅ {len(ots_creadas)} OTs creadas exitosamente para {dia_de_planificacion}.")

        # 3. Limpiar "Reservas Blandas" (Calendario) SÓLO para OPs exitosas
        if ops_planificadas_exitosamente:
            reservas_blandas_borradas = CalendarioProduccion.objects.filter(
                id_orden_produccion_id__in=ops_planificadas_exitosamente,
                fecha=dia_de_planificacion
            ).delete()
            print(f"🧹 Limpiadas {reservas_blandas_borradas[0]} reservas de calendario para OPs exitosas.")
        
            # 4. Actualizar estado de OPs exitosas
            OrdenProduccion.objects.filter(
                id_orden_produccion__in=ops_planificadas_exitosamente
            ).update(
                id_estado_orden_produccion=estado_op_planificada
            )
            print(f"✅ {len(ops_planificadas_exitosamente)} OPs marcadas como 'Planificada'.")

        # 5. Gestionar OPs que NO se pudieron planificar hoy
        if ops_fallidas_ids:
            print(f"⚠️ {len(ops_fallidas_ids)} OPs no pudieron ser planificadas hoy por el solver.")
            # Las devolvemos a "En espera" para que el MRP (Fase 1) las reprograme
            OrdenProduccion.objects.filter(
                id_orden_produccion__in=ops_fallidas_ids
            ).update(
                id_estado_orden_produccion=estado_op_en_espera
            )
            
            # Limpiamos su reserva de calendario de HOY,
            # para que el MRP (Fase 1) no piense que están ocupadas
            reservas_fallidas_borradas = CalendarioProduccion.objects.filter(
                id_orden_produccion_id__in=ops_fallidas_ids,
                fecha=dia_de_planificacion
            ).delete()
            print(f"Devueltas {len(ops_fallidas_ids)} OPs a 'En espera'. Limpiadas {reservas_fallidas_borradas[0]} reservas de calendario fallidas.")


def replanificar_produccion(fecha_objetivo=None):
    """
    Replanifica las órdenes de producción para una fecha determinada.
    Si una línea se rompe o deja de estar disponible, redistribuye las OTs.
    """

    # ✅ 1) Calcular fecha objetivo (mañana por defecto)
    if fecha_objetivo is None:
        # ❗️ USAREMOS EL MISMO DÍA DE PLANIFICACIÓN QUE EL SOLVER
        fecha_objetivo = timezone.localdate() + timezone.timedelta(days=1)
        # fecha_objetivo = timezone.localdate() + timezone.timedelta(days=1) # Versión antigua

    print(f"🔄 Replanificando producción para: {fecha_objetivo}")

    # ✅ 2) Buscar todas las OP que deberían producirse ese día
    ops = OrdenProduccion.objects.filter(
        fecha_planificada=fecha_objetivo,
        id_estado_orden_produccion__descripcion="Planificada"  # ya estaban planificadas
    )

    if not ops.exists():
        print("✅ No hay órdenes planificadas para replanificar.")
        return
    
    op_ids = list(ops.values_list('id_orden_produccion', flat=True))
    
    # ✅ 3) Buscar OTs asociadas a esas OP en estados replanificables
    estados_replanificables = EstadoOrdenTrabajo.objects.filter(
        descripcion__in=["Pendiente", "Planificada"]
    )

    ots = OrdenDeTrabajo.objects.filter(
        id_orden_produccion__in=ops,
        id_estado_orden_trabajo__in=estados_replanificables
    )

    # ✅ 4) BORRAR OTs que aún no comenzaron
    cantidad_eliminadas = ots.count()
    ots.delete()

    print(f"🗑️ Eliminadas {cantidad_eliminadas} OTs no iniciadas.")
    
    # --- ❗️ LÓGICA AÑADIDA ---
    # 5. BORRAR también las "reservas blandas" (Calendario)
    #    para este día, ya que las vamos a replanificar.
    reservas_blandas_borradas = CalendarioProduccion.objects.filter(
        id_orden_produccion_id__in=op_ids,
        fecha=fecha_objetivo
    ).delete()
    print(f"🗑️ Eliminadas {reservas_blandas_borradas[0]} reservas de calendario para replanificación.")
    # --- FIN LÓGICA AÑADIDA ---

    # ✅ 6) Devolver OP a estado Pendiente de inicio
    estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion="Pendiente de inicio")

    ops.update(id_estado_orden_produccion=estado_pendiente)

    print("🔁 OPs marcadas como Pendiente de inicio nuevamente.")

    # ✅ 7) Ejecutar el planificador normal
    # ❗️ Usar la fecha del DÍA ANTERIOR para que planifique 'fecha_objetivo'
    fecha_ejecucion_solver = fecha_objetivo - timedelta(days=1)
    ejecutar_planificador(fecha_ejecucion_solver)

    print("✅ Replanificación completada.")