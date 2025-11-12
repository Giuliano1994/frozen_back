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
    EstadoOrdenTrabajo
)

from recetas.models import ProductoLinea
from ortools.sat.python import cp_model


HORIZONTE_MINUTOS = 24 * 60
SOLVER_MAX_SECONDS = 30
SOLVER_WORKERS = 8


def ejecutar_planificador(fecha_simulada: date):

    mañana = fecha_simulada + timezone.timedelta(days=1)
    #mañana = timezone.localdate() + timezone.timedelta(days=1)

    # ✅ 1) Seleccionar solo OP para mañana
    ordenes = list(
        OrdenProduccion.objects.filter(
            id_estado_orden_produccion__descripcion="Pendiente de inicio",
            fecha_inicio__date=mañana
        ).select_related("id_producto")
    )

    # ✅ 2) Seleccionar líneas activas
    lineas = list(
        LineaProduccion.objects.filter(
            Q(id_estado_linea_produccion__descripcion="Disponible") |
            Q(id_estado_linea_produccion__descripcion="Ocupada")
        )
    )

    if not ordenes:
        print(f"✅ No hay OP para planificar mañana ({mañana}).")
        return

    if not lineas:
        print("❌ No hay líneas disponibles.")
        return

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
        print("❌ No se pudo generar una planificación.")
        return

    # ✅ Guardar resultados
    estado_ot = EstadoOrdenTrabajo.objects.get(descripcion="Pendiente")
    estado_op = EstadoOrdenProduccion.objects.get(descripcion="Planificada")

    hora_base = timezone.now()
    ots_creadas = []
    ops_cerradas = set()

    for tanda in todas_tandas:
        if solver.Value(tanda["literal"]):

            ini = solver.Value(tanda["start"])
            fin = solver.Value(tanda["end"])

            ots_creadas.append(
                OrdenDeTrabajo(
                    id_orden_produccion=tanda["op"],
                    id_linea_produccion=tanda["linea"],
                    cantidad_programada=tanda["tamano"],
                    hora_inicio_programada=hora_base + timezone.timedelta(minutes=ini),
                    hora_fin_programada=hora_base + timezone.timedelta(minutes=fin),
                    id_estado_orden_trabajo=estado_ot
                )
            )
            ops_cerradas.add(tanda["op"].id_orden_produccion)

    with transaction.atomic():
        OrdenDeTrabajo.objects.bulk_create(ots_creadas)
        OrdenProduccion.objects.filter(id_orden_produccion__in=ops_cerradas).update(
            id_estado_orden_produccion=estado_op
        )

    print(f"✅ {len(ots_creadas)} OTs creadas exitosamente según regla Producto-Linea.")


















def replanificar_produccion(fecha_objetivo=None):
    """
    Replanifica las órdenes de producción para una fecha determinada.
    Si una línea se rompe o deja de estar disponible, redistribuye las OTs.
    """

    # ✅ 1) Calcular fecha objetivo (mañana por defecto)
    if fecha_objetivo is None:
        fecha_objetivo = timezone.localdate() + timezone.timedelta(days=1)

    print(f"🔄 Replanificando producción para: {fecha_objetivo}")

    # ✅ 2) Buscar todas las OP que deberían producirse ese día
    ops = OrdenProduccion.objects.filter(
        fecha_inicio__date=fecha_objetivo,
        id_estado_orden_produccion__descripcion="Planificada"  # ya estaban planificadas
    )

    if not ops.exists():
        print("✅ No hay órdenes planificadas para replanificar.")
        return
    
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

    # ✅ 5) Devolver OP a estado Pendiente de inicio
    estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion="Pendiente de inicio")

    ops.update(id_estado_orden_produccion=estado_pendiente)

    print("🔁 OPs marcadas como Pendiente de inicio nuevamente.")

    # ✅ 6) Ejecutar el planificador normal
    ejecutar_planificador()

    print("✅ Replanificación completada.")