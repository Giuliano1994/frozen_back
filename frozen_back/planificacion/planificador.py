import math
from datetime import timedelta, date, datetime
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, F, Value
from django.db.models.functions import Coalesce
from collections import defaultdict

# --- Importar Modelos de todas las apps ---
from ventas.models import OrdenVenta, OrdenVentaProducto, EstadoVenta
from productos.models import Producto
# ❗️ Asegúrate de importar LineaProduccion y CalendarioProduccion
from produccion.models import (
    OrdenProduccion, EstadoOrdenProduccion, LineaProduccion, CalendarioProduccion
)
from compras.models import OrdenCompra, OrdenCompraMateriaPrima, EstadoOrdenCompra
from stock.models import (
    LoteProduccion, LoteMateriaPrima, EstadoLoteProduccion,
    EstadoLoteMateriaPrima, ReservaStock, ReservaMateriaPrima,
    EstadoReserva, EstadoReservaMateria
)
# --- IMPORTAR SERVICIOS DE STOCK (Clave) ---
from stock.services import get_stock_disponible_para_producto, get_stock_disponible_para_materia_prima
# ❗️ Asegúrate de importar ProductoLinea
from recetas.models import ProductoLinea, Receta, RecetaMateriaPrima
from materias_primas.models import MateriaPrima, Proveedor

# --- Constantes de Planificación (Centralizadas) ---
HORAS_LABORABLES_POR_DIA = 16
DIAS_BUFFER_ENTREGA_PT = 1
DIAS_BUFFER_RECEPCION_MP = 1

# ===================================================================
# FUNCIONES HELPER
# (_reservar_stock_pt y _reservar_stock_mp no cambian)
# ===================================================================

@transaction.atomic
def _reservar_stock_pt(linea_ov: OrdenVentaProducto, cantidad_a_reservar: int, estado_activa: EstadoReserva):
    # ... (Tu código helper _reservar_stock_pt) ...
    filtro_reservas_activas = Q(reservas__id_estado_reserva__descripcion='Activa')
    lotes_disponibles = LoteProduccion.objects.filter(
        id_producto=linea_ov.id_producto,
        id_estado_lote_produccion__descripcion="Disponible"
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    ).annotate(
        disponible=F('cantidad') - F('total_reservado')
    ).filter(
        disponible__gt=0
    ).order_by('fecha_vencimiento')
    cantidad_pendiente = cantidad_a_reservar
    for lote in lotes_disponibles:
        if cantidad_pendiente <= 0: break
        disponible_lote = lote.disponible 
        cantidad_a_tomar = min(disponible_lote, cantidad_pendiente)
        if cantidad_a_tomar > 0:
            ReservaStock.objects.create(
                id_orden_venta_producto=linea_ov,
                id_lote_produccion=lote,
                cantidad_reservada=cantidad_a_tomar,
                id_estado_reserva=estado_activa
            )
            cantidad_pendiente -= cantidad_a_tomar
    print(f"      > (OV {linea_ov.id_orden_venta_id}) Reservados {cantidad_a_reservar - cantidad_pendiente} de {cantidad_a_reservar} de {linea_ov.id_producto.nombre}")

@transaction.atomic
def _reservar_stock_mp(op: OrdenProduccion, mp_id: int, cantidad_a_reservar: int, estado_activa: EstadoReservaMateria):
    # ... (Tu código helper _reservar_stock_mp) ...
    filtro_reservas_activas = Q(reservas__id_estado_reserva_materia__descripcion='Activa')
    lotes_disponibles_mp = LoteMateriaPrima.objects.filter(
        id_materia_prima_id=mp_id,
        id_estado_lote_materia_prima__descripcion="disponible"
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    ).annotate(
        disponible=F('cantidad') - F('total_reservado')
    ).filter(
        disponible__gt=0
    ).order_by('fecha_vencimiento')
    cantidad_pendiente = cantidad_a_reservar
    for lote_mp in lotes_disponibles_mp:
        if cantidad_pendiente <= 0: break
        disponible_lote = lote_mp.disponible 
        cantidad_a_tomar = min(disponible_lote, cantidad_pendiente)
        if cantidad_a_tomar > 0:
            ReservaMateriaPrima.objects.create(
                id_orden_produccion=op,
                id_lote_materia_prima=lote_mp,
                cantidad_reservada=cantidad_a_tomar,
                id_estado_reserva_materia=estado_activa
            )
            cantidad_pendiente -= cantidad_a_tomar
    print(f"      > (OP {op.id_orden_produccion}) Reservados {cantidad_a_reservar - cantidad_pendiente} de {cantidad_a_reservar} de MP {mp_id}")


# ===================================================================
# FUNCIÓN PRINCIPAL DEL PLANIFICADOR
# ===================================================================

@transaction.atomic
def ejecutar_planificacion_diaria_mrp(fecha_simulada: date):
    """
    Ejecuta el proceso completo de MRP Híbrido (JIT + Planificación).
    - PASO 1-2: Calcula demanda neta y realiza "Pegging" (vincula OVs).
    - PASO 3: Reservas JIT para mañana.
    - PASO 4: Netting + Scheduling (Capacidad Finita) + Reprogramación de OVs.
    - PASO 5: Cálculo de MP y asignación de estado (En espera / Pendiente de inicio).
    - PASO 6: Creación de OCs.
    """
    hoy = fecha_simulada
    tomorrow = hoy + timedelta(days=1)
    fecha_limite_ov = hoy + timedelta(days=7)
    
    print(f"--- INICIANDO PLANIFICADOR MRP DIARIO ({hoy}) ---")
    print(f"--- Alcance: Órdenes de Venta hasta {fecha_limite_ov} ---")
    print(f"--- Día de Reserva JIT: {tomorrow} ---")

    # --- Obtener Estados ---
    estado_ov_creada = EstadoVenta.objects.get(descripcion="Creada")
    estado_ov_en_preparacion, _ = EstadoVenta.objects.get_or_create(descripcion="En Preparación")
    estado_ov_pendiente_pago, _ = EstadoVenta.objects.get_or_create(descripcion="Pendiente de Pago")
    
    estado_op_en_espera, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="En espera")
    estado_op_pendiente_inicio, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="Pendiente de inicio")
    estado_op_en_proceso, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="En proceso")
    estado_op_cancelada, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="Cancelado")
    estado_op_planificada, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="Planificada")
    
    estado_oc_en_proceso, _ = EstadoOrdenCompra.objects.get_or_create(descripcion="En proceso")
    estado_reserva_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_reserva_mp_activa, _ = EstadoReservaMateria.objects.get_or_create(descripcion="Activa")
    
    # ===================================================================
    # PASO 1 y 2: VERIFICAR ÓRDENES DE LA SEMANA Y CALCULAR DEMANDA NETA DE PT
    # ===================================================================
    print("\n[PASO 1-2/6] Verificando OVs de la semana y calculando demanda neta de PT...")

    ordenes_semana = OrdenVenta.objects.filter(
        id_estado_venta__in=[estado_ov_creada, estado_ov_en_preparacion, estado_ov_pendiente_pago],
        fecha_entrega__range=[hoy, fecha_limite_ov]
    ).prefetch_related('ordenventaproducto_set__id_producto').order_by('fecha_entrega', 'id_prioridad__id_prioridad')

    productos_en_demanda_ids = OrdenVentaProducto.objects.filter(
        id_orden_venta__in=ordenes_semana
    ).values_list('id_producto_id', flat=True).distinct()
    
    productos_en_demanda = Producto.objects.filter(pk__in=productos_en_demanda_ids)
    
    stock_virtual_pt = {
        p.id_producto: get_stock_disponible_para_producto(p.id_producto)
        for p in productos_en_demanda
    }
    
    # ❗️ CAMBIO: Añadido "fuentes" para el Pegging
    demanda_neta_produccion = defaultdict(lambda: {
        "cantidad": 0, 
        "fecha_mas_temprana": date(9999, 12, 31),
        "umbral_minimo": 0,
        "fuentes": []  # Guarda las OVs que piden esto
    })
    
    reservas_jit_para_manana = {}
    ordenes_para_actualizar_estado = {}

    for ov in ordenes_semana:
        print(f"   Analizando OV {ov.id_orden_venta} (Entrega: {ov.fecha_entrega.date()})...")
        orden_esta_completa = True
        
        for linea_ov in ov.ordenventaproducto_set.all():
            producto_id = linea_ov.id_producto_id
            producto = linea_ov.id_producto
            
            reservado_activo = ReservaStock.objects.filter(
                id_orden_venta_producto=linea_ov, 
                id_estado_reserva=estado_reserva_activa
            ).aggregate(total=Sum('cantidad_reservada'))['total'] or 0
            
            cantidad_faltante_a_reservar = linea_ov.cantidad - reservado_activo
            if cantidad_faltante_a_reservar <= 0:
                continue

            stock_disp = stock_virtual_pt.get(producto_id, 0)
            
            tomar_de_stock = min(stock_disp, cantidad_faltante_a_reservar)
            cantidad_para_producir = cantidad_faltante_a_reservar - tomar_de_stock

            if tomar_de_stock > 0:
                stock_virtual_pt[producto_id] -= tomar_de_stock
                if ov.fecha_entrega.date() == tomorrow:
                    reservas_jit_para_manana[linea_ov.id_orden_venta_producto] = tomar_de_stock
                else:
                    print(f"      > (OV {ov.id_orden_venta}) Stock de {producto.nombre} encontrado, pero no se reserva (Entrega: {ov.fecha_entrega.date()})")

            if cantidad_para_producir > 0:
                orden_esta_completa = False
                demanda_neta = demanda_neta_produccion[producto_id]
                demanda_neta["cantidad"] += cantidad_para_producir
                demanda_neta["umbral_minimo"] = producto.umbral_minimo
                if ov.fecha_entrega.date() < demanda_neta["fecha_mas_temprana"]:
                    demanda_neta["fecha_mas_temprana"] = ov.fecha_entrega.date()
                
                # --- ❗️ INICIO DEL CAMBIO (PEGGING) ---
                # Guardamos qué línea de OV generó esta demanda
                demanda_neta["fuentes"].append({
                    "linea_ov_id": linea_ov.id_orden_venta_producto,
                    "fecha_entrega_requerida": ov.fecha_entrega.date()
                })
                # --- FIN DEL CAMBIO ---

        if orden_esta_completa:
            if not reservas_jit_para_manana: 
                 ordenes_para_actualizar_estado[ov.id_orden_venta] = estado_ov_pendiente_pago
        else:
            ordenes_para_actualizar_estado[ov.id_orden_venta] = estado_ov_en_preparacion

    # ===================================================================
    # PASO 3: EJECUTAR RESERVAS JIT (Req 3)
    # ===================================================================
    print(f"\n[PASO 3/6] Reservando stock de PT (Just-in-Time) para {len(reservas_jit_para_manana)} líneas de mañana...")
    
    for linea_ov_id, cantidad in reservas_jit_para_manana.items():
        try:
            linea_a_reservar = OrdenVentaProducto.objects.get(pk=linea_ov_id)
            print(f"   > Reservando JIT: {cantidad} de {linea_a_reservar.id_producto.nombre} para OV {linea_a_reservar.id_orden_venta_id}")
            _reservar_stock_pt(linea_a_reservar, cantidad, estado_reserva_activa)
            orden_jit = linea_a_reservar.id_orden_venta
            if orden_jit.id_orden_venta not in ordenes_para_actualizar_estado:
                 ordenes_para_actualizar_estado[orden_jit.id_orden_venta] = estado_ov_pendiente_pago

        except OrdenVentaProducto.DoesNotExist:
            print(f"   !ERROR: No se encontró la línea de OV {linea_ov_id} para reservar.")
            
    for ov_id, estado in ordenes_para_actualizar_estado.items():
        OrdenVenta.objects.filter(pk=ov_id).update(id_estado_venta=estado)

    # ===================================================================
    # PASO 4: NETTING, SCHEDULING (CAPACIDAD FINITA) Y CREACIÓN DE OPS
    # ===================================================================
    print(f"\n[PASO 4/6] Netting, Scheduling (Capacidad Finita) y Creación de OPs...")

    # --- Pools de Stock (Movidos del antiguo PASO 5) ---
    productos_en_produccion_ids = OrdenProduccion.objects.filter(
        id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio, estado_op_en_proceso, estado_op_planificada]
    ).values_list('id_producto_id', flat=True)

    todos_los_productos_ids = set(demanda_neta_produccion.keys()) | set(productos_en_produccion_ids)
    print(f"   > Analizando {len(todos_los_productos_ids)} productos para netting y scheduling...")
    
    compras_agregadas_por_proveedor = defaultdict(lambda: {
        "proveedor": None,
        "fecha_requerida_mas_temprana": date(9999, 12, 31),
        "items": defaultdict(int) 
    })
    
    mp_ids_necesarios_global = RecetaMateriaPrima.objects.filter(
        id_receta__id_producto_id__in=todos_los_productos_ids
    ).values_list('id_materia_prima_id', flat=True).distinct()
    
    stock_virtual_mp = {
        mp_id: get_stock_disponible_para_materia_prima(mp_id)
        for mp_id in mp_ids_necesarios_global
    }

    print("   > Obteniendo pool de stock 'En Camino' (OCs en proceso)...")
    compras_en_proceso = OrdenCompraMateriaPrima.objects.filter(
        id_orden_compra__id_estado_orden_compra=estado_oc_en_proceso
    )
    stock_virtual_oc = defaultdict(int)
    for item in compras_en_proceso:
        stock_virtual_oc[item.id_materia_prima_id] += item.cantidad
    print(f"   > Pool de OCs en camino: {dict(stock_virtual_oc)}")
    # --- Fin Pools de Stock ---

    for producto_id in todos_los_productos_ids:
        op = None
        created = False
        producto = Producto.objects.get(pk=producto_id)
        
        # 1. ¿CUÁNTO NECESITAMOS?
        info_demanda = demanda_neta_produccion.get(producto_id, {})
        cantidad_faltante_demanda = info_demanda.get('cantidad', 0)
        stock_proyectado_final = stock_virtual_pt.get(producto_id, 0)
        necesidad_stock_minimo = max(0, producto.umbral_minimo - stock_proyectado_final)
        
        necesidad_total_produccion = cantidad_faltante_demanda + necesidad_stock_minimo
        fecha_entrega_ov_mas_temprana = info_demanda.get('fecha_mas_temprana', hoy + timedelta(days=7))

        # 2. ¿CUÁNTO TENEMOS EN PRODUCCIÓN?
        ops_existentes_query = OrdenProduccion.objects.filter(
            id_producto=producto, 
            id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio, estado_op_en_proceso, estado_op_planificada]
        )
        ops_fijas_query = ops_existentes_query.filter(
            id_estado_orden_produccion__in=[estado_op_pendiente_inicio, estado_op_en_proceso, estado_op_planificada]
        )
        total_en_produccion_fija = ops_fijas_query.aggregate(total=Sum('cantidad'))['total'] or 0
        
        op_existente_en_espera = ops_existentes_query.filter(
            id_estado_orden_produccion=estado_op_en_espera,
        ).first()
        
        total_en_produccion_existente = ops_existentes_query.aggregate(total=Sum('cantidad'))['total'] or 0
        
        # 3. EL BALANCE
        balance = necesidad_total_produccion - total_en_produccion_existente
        cantidad_objetivo_en_espera = max(0, necesidad_total_produccion - total_en_produccion_fija)
        
        print(f"   > Netting {producto.nombre}: Demanda Total={necesidad_total_produccion} - OPs en Curso={total_en_produccion_existente} = Balance={balance}")

        if cantidad_objetivo_en_espera > 0:
            # --- FALTANTE: INICIA LÓGICA DE SCHEDULING (CAPACIDAD FINITA) ---
            print(f"      > Faltan {cantidad_objetivo_en_espera} unidades netas. Buscando capacidad finita...")
            
            cantidad_a_producir_total = cantidad_objetivo_en_espera 
            
            try:
                # --- A. CÁLCULO DE TIEMPO DE PRODUCCIÓN (LÓGICA PARALELO) ---
                capacidades_linea = ProductoLinea.objects.filter(id_producto=producto)
                if not capacidades_linea.exists():
                    print(f"      !ERROR: {producto.nombre} no tiene líneas asignadas en 'ProductoLinea'. Omitiendo OP.")
                    continue

                cant_total_por_hora = capacidades_linea.aggregate(
                    total=Sum('cant_por_hora')
                )['total'] or 0

                if cant_total_por_hora <= 0:
                    print(f"      !ERROR: {producto.nombre} tiene capacidad total 0/hr. Omitiendo OP.")
                    continue

                # ❗️ CAMBIO: Usamos float para horas necesarias (ej. 10.5 horas)
                horas_necesarias_totales = float(cantidad_a_producir_total) / float(cant_total_por_hora)
                dias_produccion_estimados = math.ceil(horas_necesarias_totales / HORAS_LABORABLES_POR_DIA)
                
                print(f"      > Necesita {horas_necesarias_totales:.2f} horas-máquina totales (aprox. {dias_produccion_estimados} días).")

                # --- B. CÁLCULO DE FECHA IDEAL DE INICIO ---
                fecha_planificada_ideal = fecha_entrega_ov_mas_temprana - timedelta(days=dias_produccion_estimados) - timedelta(DIAS_BUFFER_ENTREGA_PT)
                
                if fecha_planificada_ideal < hoy:
                    fecha_planificada_ideal = hoy

                # --- C. CREAR/ACTUALIZAR LA OP (Primero) ---
                if op_existente_en_espera:
                    op = op_existente_en_espera
                    op.cantidad = cantidad_a_producir_total
                    op.fecha_planificada = fecha_planificada_ideal # Temporal
                    op.save(update_fields=['cantidad', 'fecha_planificada'])
                    created = False
                else:
                    op = OrdenProduccion.objects.create(
                        id_producto=producto,
                        id_estado_orden_produccion=estado_op_en_espera, # Default
                        cantidad=cantidad_a_producir_total,
                        fecha_planificada=fecha_planificada_ideal # Temporal
                    )
                    created = True
                
                # Limpiamos reservas de MP y Calendario viejas
                CalendarioProduccion.objects.filter(id_orden_produccion=op).delete()
                ReservaMateriaPrima.objects.filter(id_orden_produccion=op).delete()

                # --- D. LÓGICA "WALK THE CALENDAR" (Bucle Único) ---
                horas_pendientes = horas_necesarias_totales
                fecha_a_buscar = fecha_planificada_ideal
                fecha_inicio_real_asignada = None
                fecha_fin_real_asignada = None
                
                reservas_a_crear_bulk = []
                print(f"      > Buscando hueco desde {fecha_a_buscar}...")

                while horas_pendientes > 0:
                    # 3a. ¿Cuántas horas libres (ENTERAS) tienen las líneas ESE DÍA?
                    horas_libres_cuello_botella = HORAS_LABORABLES_POR_DIA
                    
                    lineas_ids_producto = [c.id_linea_produccion_id for c in capacidades_linea]
                    
                    carga_existente = CalendarioProduccion.objects.filter(
                        id_linea_produccion_id__in=lineas_ids_producto,
                        fecha=fecha_a_buscar,
                        id_orden_produccion__id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio]
                    ).exclude(
                        id_orden_produccion=op
                    ).values(
                        'id_linea_produccion_id'
                    ).annotate(
                        total_reservado=Sum('horas_reservadas')
                    ).values('id_linea_produccion_id', 'total_reservado')
                    
                    carga_por_linea = {c['id_linea_produccion_id']: float(c['total_reservado']) for c in carga_existente}

                    for linea_id in lineas_ids_producto:
                        carga_dia = carga_por_linea.get(linea_id, 0.0)
                        horas_libres_linea = max(0, HORAS_LABORABLES_POR_DIA - carga_dia)
                        horas_libres_cuello_botella = min(horas_libres_cuello_botella, horas_libres_linea)

                    # ❗️ REQUERIMIENTO 1: Usar solo horas enteras (floor)
                    horas_libres_enteras = math.floor(horas_libres_cuello_botella)

                    # 3b. Asignar tiempo
                    if horas_libres_enteras <= 0:
                        # No hay horas enteras libres hoy, pasar al siguiente día
                        fecha_a_buscar += timedelta(days=1)
                        continue
                        
                    horas_a_reservar_hoy = min(horas_pendientes, horas_libres_enteras)

                    # ❗️ REQUERIMIENTO 2 y 3: Preparamos la reserva con cantidad
                    for cap_linea in capacidades_linea:
                        # Cuántas unidades produce esta línea en este bloque de tiempo
                        cantidad_dia_linea = round(float(horas_a_reservar_hoy) * float(cap_linea.cant_por_hora))
                        
                        if horas_a_reservar_hoy > 0:
                            reservas_a_crear_bulk.append(
                                CalendarioProduccion(
                                    id_orden_produccion=op,
                                    id_linea_produccion=cap_linea.id_linea_produccion,
                                    fecha=fecha_a_buscar,
                                    horas_reservadas=horas_a_reservar_hoy,
                                    cantidad_a_producir=cantidad_dia_linea
                                )
                            )
                    
                    horas_pendientes -= horas_a_reservar_hoy
                    
                    if fecha_inicio_real_asignada is None:
                        fecha_inicio_real_asignada = fecha_a_buscar
                    
                    print(f"      > Reservadas {horas_a_reservar_hoy}hs en {fecha_a_buscar}. Faltan {horas_pendientes:.2f}hs.")

                    # 3c. Pasar al siguiente día
                    fecha_a_buscar += timedelta(days=1)
                
                # La fecha de fin es el último día que tocamos (un día antes de donde paró el bucle)
                fecha_fin_real_asignada = fecha_a_buscar - timedelta(days=1)


                # --- E. GUARDAR OP Y RESERVAS DE CALENDARIO ---
                op.fecha_planificada = fecha_inicio_real_asignada
                op.fecha_fin_planificada = fecha_fin_real_asignada
                op.save(update_fields=['fecha_planificada', 'fecha_fin_planificada'])
                
                CalendarioProduccion.objects.bulk_create(reservas_a_crear_bulk)
                
                if created:
                     print(f"      -> CREADA OP {op.id_orden_produccion} para {cantidad_a_producir_total} de {producto.nombre}.")
                else:
                     print(f"      -> ACTUALIZADA OP {op.id_orden_produccion}. Total ahora es {op.cantidad}.")
                print(f"      -> PLANIFICACIÓN REAL: {op.fecha_planificada} a {op.fecha_fin_planificada}.")


                # --- ❗️ REQUERIMIENTO 1 (MEJORADO): REPROGRAMACIÓN AUTOMÁTICA DE OVs ---
                
                fuentes_demanda = info_demanda.get('fuentes', [])
                ovs_afectadas = set() 

                for fuente in fuentes_demanda:
                    fecha_entrega_ov_original = fuente["fecha_entrega_requerida"]
                    linea_ov_id = fuente["linea_ov_id"]
                    
                    fecha_limite_produccion = fecha_entrega_ov_original - timedelta(days=DIAS_BUFFER_ENTREGA_PT)
                    
                    if op.fecha_fin_planificada > fecha_limite_produccion:
                        print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                        print(f"      !!! ALERTA DE ENTREGA: OP {op.id_orden_produccion} (Producto: {producto.nombre})")
                        print(f"      !!! Vinculada a: Línea OV {linea_ov_id} (Entrega: {fecha_entrega_ov_original})")
                        print(f"      !!! Producción termina el: {op.fecha_fin_planificada}")
                        print(f"      !!! Pero la OV la requiere para (máx): {fecha_limite_produccion}")
                        print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                        
                        try:
                            linea_ov = OrdenVentaProducto.objects.select_related('id_orden_venta').get(pk=linea_ov_id)
                            ov_a_reprogramar = linea_ov.id_orden_venta
                            
                            nueva_fecha_entrega_sugerida = op.fecha_fin_planificada + timedelta(days=DIAS_BUFFER_ENTREGA_PT)
                            
                            if nueva_fecha_entrega_sugerida > ov_a_reprogramar.fecha_entrega.date():
                                print(f"      !!! DESPLAZANDO OV {ov_a_reprogramar.id_orden_venta} de {ov_a_reprogramar.fecha_entrega.date()} a {nueva_fecha_entrega_sugerida}")
                                ov_a_reprogramar.fecha_entrega = nueva_fecha_entrega_sugerida
                                ov_a_reprogramar.id_estado_venta = estado_ov_en_preparacion 
                                ov_a_reprogramar.save(update_fields=['fecha_entrega', 'id_estado_venta'])
                                ovs_afectadas.add(ov_a_reprogramar.id_orden_venta)
                            
                        except OrdenVentaProducto.DoesNotExist:
                            print(f"      !ERROR: No se pudo encontrar la línea OV {linea_ov_id} para reprogramarla.")
                
                if ovs_afectadas:
                    print(f"      -> Se reprogramaron {len(ovs_afectadas)} OVs ({list(ovs_afectadas)}) debido a retrasos de capacidad.")
                
                # --- FIN REQUERIMIENTO 1 ---

                # --- F. LÓGICA DE LOTE (Mantenida) ---
                if created or not op.id_lote_produccion:
                    try:
                        estado_lote_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")
                        dias_duracion = getattr(producto, 'dias_duracion', 0) or 0
                        
                        lote = LoteProduccion.objects.create(
                            id_producto=op.id_producto,
                            id_estado_lote_produccion=estado_lote_espera,
                            cantidad=op.cantidad,
                            fecha_produccion=timezone.now().date(), 
                            fecha_vencimiento=timezone.now().date() + timedelta(days=dias_duracion)
                        )
                        op.id_lote_produccion = lote
                        op.save(update_fields=['id_lote_produccion'])
                        print(f"      -> CREADO LoteProduccion {lote.id_lote_produccion} y asignado a OP {op.id_orden_produccion}")

                    except EstadoLoteProduccion.DoesNotExist:
                        print(f"      !ERROR CRÍTICO: No se pudo crear Lote. Estado 'En espera' no existe.")
                elif op and not created and op.id_lote_produccion:
                    op.id_lote_produccion.cantidad = op.cantidad
                    op.id_lote_produccion.save()


                # ===================================================================
                # PASO 5: RESERVAR MP Y CREAR OCS (INTEGRADO)
                # ===================================================================
                print(f"      > [PASO 5/6] Calculando MP y Estado para OP {op.id_orden_produccion}...")
                
                receta = Receta.objects.get(id_producto=op.id_producto)
                ingredientes_totales = RecetaMateriaPrima.objects.filter(id_receta=receta)
                
                max_lead_time_mp = 0
                
                # ❗️ REQUERIMIENTO 2: Lógica de Estado
                op_tiene_todo_el_material_EN_STOCK = True

                for ingr in ingredientes_totales:
                    mp_id = ingr.id_materia_prima_id
                    mp = ingr.id_materia_prima
                    proveedor = mp.id_proveedor
                    
                    cantidad_requerida_op = ingr.cantidad * op.cantidad
                    
                    # (Las reservas de MP ya se limpiaron arriba)
                    cantidad_faltante_op = cantidad_requerida_op

                    if cantidad_faltante_op <= 0:
                        continue
                    
                    # 1. Intentar tomar de stock físico
                    stock_mp_disponible = stock_virtual_mp.get(mp_id, 0)
                    tomar_de_stock = min(stock_mp_disponible, cantidad_faltante_op)
                    
                    if tomar_de_stock > 0:
                        print(f"      > Reservando {tomar_de_stock} de MP {mp_id} (stock) para OP {op.id_orden_produccion}")
                        _reservar_stock_mp(op, mp_id, tomar_de_stock, estado_reserva_mp_activa)
                        stock_virtual_mp[mp_id] -= tomar_de_stock
                        cantidad_faltante_op -= tomar_de_stock
                    
                    if cantidad_faltante_op <= 0:
                        continue
                        
                    op_tiene_todo_el_material_EN_STOCK = False
                        
                    # 2. Intentar "reservar" de stock en camino
                    stock_oc_disponible = stock_virtual_oc.get(mp_id, 0)
                    tomar_de_oc = min(stock_oc_disponible, cantidad_faltante_op)
                    
                    if tomar_de_oc > 0:
                        stock_virtual_oc[mp_id] -= tomar_de_oc
                        cantidad_faltante_op -= tomar_de_oc
                    
                    if cantidad_faltante_op <= 0:
                        continue
                    
                    # 3. Lo que queda, hay que comprarlo
                    cantidad_a_comprar = cantidad_faltante_op
                    
                    if cantidad_a_comprar > 0:
                        print(f"      ! Faltan {cantidad_a_comprar} de {mp.nombre} para OP {op.id_orden_produccion}. Agregando a OC.")
                        
                        lead_proveedor = ingr.id_materia_prima.id_proveedor.lead_time_days
                        max_lead_time_mp = max(max_lead_time_mp, lead_proveedor)
                        
                        compra_agregada = compras_agregadas_por_proveedor[proveedor.id_proveedor]
                        compra_agregada["proveedor"] = proveedor
                        compra_agregada["items"][mp_id] += cantidad_a_comprar
                        
                        fecha_requerida_mp = op.fecha_planificada - timedelta(days=DIAS_BUFFER_RECEPCION_MP)
                        
                        if fecha_requerida_mp < compra_agregada["fecha_requerida_mas_temprana"]:
                            compra_agregada["fecha_requerida_mas_temprana"] = fecha_requerida_mp
                
                # --- G. ACTUALIZAR fecha_inicio (compra) Y ESTADO en la OP ---
                
                if op_tiene_todo_el_material_EN_STOCK:
                    op.id_estado_orden_produccion = estado_op_pendiente_inicio
                    print(f"      > OP {op.id_orden_produccion} tiene toda la MP en Stock. Estado -> Pendiente de inicio")
                else:
                    op.id_estado_orden_produccion = estado_op_en_espera
                    print(f"      > OP {op.id_orden_produccion} esperando MP (en tránsito o por comprar). Estado -> En espera")

                op.fecha_inicio = op.fecha_planificada - timedelta(days=max_lead_time_mp + DIAS_BUFFER_RECEPCION_MP)
                op.save(update_fields=['fecha_inicio', 'id_estado_orden_produccion'])

            except Receta.DoesNotExist:
                print(f"      !ERROR: {producto.nombre} no tiene Receta. Omitiendo OP.")
                if created and op.pk: op.delete() # Borra la OP fallida
                CalendarioProduccion.objects.filter(id_orden_produccion=op).delete()
            except Exception as e:
                print(f"      !ERROR al planificar OP para {producto.nombre}: {e}")
                if created and op.pk: op.delete() # Borra la OP fallida
                CalendarioProduccion.objects.filter(id_orden_produccion=op).delete()

        elif balance < 0:
            # --- SOBRANTE: Necesitamos cancelar OPs ---
            cantidad_a_cancelar = abs(balance)
            print(f"   > {producto.nombre}: Demanda ({necesidad_total_produccion}) < Producción ({total_en_produccion_existente}). Sobran {cantidad_a_cancelar}. Cancelando OPs 'En espera'...")
            
            ops_en_espera_a_cancelar = ops_existentes_query.filter(id_estado_orden_produccion=estado_op_en_espera).order_by('-fecha_inicio')
            
            for op_cancelar in ops_en_espera_a_cancelar:
                if cantidad_a_cancelar <= 0: break
                
                # ❗️ Borrar también sus reservas de calendario y MP
                CalendarioProduccion.objects.filter(id_orden_produccion=op_cancelar).delete()
                ReservaMateriaPrima.objects.filter(id_orden_produccion=op_cancelar).delete()
                
                if op_cancelar.cantidad <= cantidad_a_cancelar:
                    op_cancelar.id_estado_orden_produccion = estado_op_cancelada
                    op_cancelar.save()
                    cantidad_a_cancelar -= op_cancelar.cantidad
                    print(f"      -> CANCELADA OP {op_cancelar.id_orden_produccion} (completa: {op_cancelar.cantidad} unidades)")
                else:
                    op_cancelar.cantidad -= cantidad_a_cancelar
                    op_cancelar.save()
                    print(f"      -> REDUCIDA OP {op_cancelar.id_orden_produccion} en {cantidad_a_cancelar} unidades. (Nueva cant: {op_cancelar.cantidad})")
                    # La dejamos "En espera" para que el próximo MRP la re-planifique
                    cantidad_a_cancelar = 0

            if cantidad_a_cancelar > 0:
                print(f"      !ALERTA: Aún sobran {cantidad_a_cancelar} unidades, pero no hay más OPs 'En espera' para cancelar.")
            
    # ===================================================================
    # PASO 6: CREAR ÓRDENES DE COMPRA (AGRUPADAS)
    # ===================================================================
    print(f"\n[PASO 6/6] Creando {len(compras_agregadas_por_proveedor)} OCs agrupadas por proveedor...")

    for proveedor_id, info in compras_agregadas_por_proveedor.items():
        proveedor = info["proveedor"]
        fecha_necesaria_mp = info["fecha_requerida_mas_temprana"]
        
        lead_time = proveedor.lead_time_days
        fecha_entrega_oc = fecha_necesaria_mp
        fecha_solicitud_oc = fecha_entrega_oc - timedelta(days=lead_time)

        if fecha_solicitud_oc < hoy:
            fecha_solicitud_oc = hoy
            fecha_entrega_oc = hoy + timedelta(days=lead_time)
            print(f"   !ALERTA OC: Pedido a {proveedor.nombre} está retrasado. Nueva entrega: {fecha_entrega_oc}")
            
        oc, created = OrdenCompra.objects.get_or_create(
            id_proveedor=proveedor,
            id_estado_orden_compra=estado_oc_en_proceso,
            fecha_entrega_estimada=fecha_entrega_oc,
            defaults={'fecha_solicitud': fecha_solicitud_oc}
        )
        if created:
            print(f"   > Generando NUEVA OC {oc.id_orden_compra} para {proveedor.nombre} (Entrega: {fecha_entrega_oc})")
        else:
            print(f"   > Usando OC EXISTENTE {oc.id_orden_compra} para {proveedor.nombre} (Entrega: {fecha_entrega_oc})")
        
        for mp_id, cantidad_necesaria_hoy in info["items"].items():
    
            item_oc, item_created = OrdenCompraMateriaPrima.objects.get_or_create(
                id_orden_compra=oc,
                id_materia_prima_id=mp_id,
                defaults={'cantidad': cantidad_necesaria_hoy}
            )
            
            if item_created:
                print(f"      - NUEVO Item: {cantidad_necesaria_hoy} de MP {mp_id} añadido a OC {oc.id_orden_compra}.")
            else:
                item_oc.cantidad = cantidad_necesaria_hoy 
                item_oc.save()
                print(f"      - Item existente (MP {mp_id}) en OC {oc.id_orden_compra} ACTUALIZADO a {cantidad_necesaria_hoy}.")

    print("\n--- PLANIFICADOR MRP FINALIZADO ---")