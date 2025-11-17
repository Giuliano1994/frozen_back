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
from produccion.models import (
    OrdenProduccion, EstadoOrdenProduccion, LineaProduccion, 
    CalendarioProduccion, OrdenProduccionPegging
)
from compras.models import OrdenCompra, OrdenCompraMateriaPrima, EstadoOrdenCompra
from stock.models import (
    LoteProduccion, LoteMateriaPrima, EstadoLoteProduccion,
    EstadoLoteMateriaPrima, ReservaStock, ReservaMateriaPrima,
    EstadoReserva, EstadoReservaMateria
)
from stock.services import get_stock_disponible_para_producto, get_stock_disponible_para_materia_prima
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
    estado_op_cancelada, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="Cancelado")
    
    estado_oc_en_proceso, _ = EstadoOrdenCompra.objects.get_or_create(descripcion="En proceso")
    estado_reserva_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_reserva_mp_activa, _ = EstadoReservaMateria.objects.get_or_create(descripcion="Activa")
    
    # --- Pools de Stock (Se inicializan 1 vez) ---
    print("   > Obteniendo pools de stock (MP y OCs)...")
    stock_virtual_mp = {
        mp.id_materia_prima: get_stock_disponible_para_materia_prima(mp.id_materia_prima)
        for mp in MateriaPrima.objects.all()
    }
    compras_en_proceso = OrdenCompraMateriaPrima.objects.filter(
        id_orden_compra__id_estado_orden_compra=estado_oc_en_proceso
    )
    stock_virtual_oc = defaultdict(int)
    for item in compras_en_proceso:
        stock_virtual_oc[item.id_materia_prima_id] += item.cantidad
    

    print("   > Ajustando stock virtual (OCs) según demanda de OPs en curso...")
    
    # 1. Buscar OPs activas que todavía están esperando materiales o por iniciar
    ops_activas_ajuste = OrdenProduccion.objects.filter(
        id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio]
    )

    total_descontado_de_oc = 0

    for op in ops_activas_ajuste:
        try:
            # Obtenemos la receta para saber qué consume esta OP realmente
            receta = Receta.objects.get(id_producto=op.id_producto)
            ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
            
            for ing in ingredientes:
                mp_id = ing.id_materia_prima_id
                
                # A. Cuánto necesita la OP en total
                cantidad_total_requerida = ing.cantidad * op.cantidad
                
                # B. Cuánto YA tiene asegurado físicamente (Reservas reales en BD)
                # (Esto ya fue descontado de 'stock_virtual_mp' por la función get_stock_disponible...)
                reservas_fisicas = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=op,
                    id_lote_materia_prima__id_materia_prima_id=mp_id
                ).aggregate(total=Sum('cantidad_reservada'))['total'] or 0
                
                # C. Cuánto le falta (esto es lo que "come" de las OCs en camino)
                demanda_pendiente = cantidad_total_requerida - reservas_fisicas
                
                if demanda_pendiente > 0:
                    # Restamos esa demanda del pool de Compras (stock_virtual_oc)
                    # Si el pool llega a cero o negativo, el Paso 6 generará compras nuevas. Correcto.
                    stock_virtual_oc[mp_id] -= demanda_pendiente
                    total_descontado_de_oc += demanda_pendiente

        except Receta.DoesNotExist:
            print(f"     ⚠️ OP {op.id_orden_produccion} no tiene receta. No se puede descontar stock.")

    print(f"   > Total descontado de OCs en camino (comprometido): {total_descontado_de_oc}")


    # Diccionario para agrupar compras (Se inicializa 1 vez)
    compras_agregadas_por_proveedor = defaultdict(lambda: {
        "proveedor": None,
        "fecha_requerida_mas_temprana": date(9999, 12, 31),
        "items": defaultdict(int) 
    })
    
    # ===================================================================
    # 🆕 PASO 0: CIERRE DE OVs PARA MAÑANA
    # (Reservar Stock PT y cambiar estado a 'Pendiente de Pago')
    # ===================================================================
    print(f"\n[PASO 0] Verificando entregas para mañana ({tomorrow}) para paso a 'Pendiente de Pago'...")

    # 1. Buscar OVs en 'En Preparación' que se entreguen mañana
    ovs_cierre = OrdenVenta.objects.filter(
        id_estado_venta=estado_ov_en_preparacion,
        fecha_entrega__date=tomorrow
    )

    for ov in ovs_cierre:
        print(f"   > Procesando cierre de OV {ov.id_orden_venta}...")
        todas_lineas_listas = True
        
        lineas = OrdenVentaProducto.objects.filter(id_orden_venta=ov)
        
        for linea in lineas:
            # A. Calcular cuánto falta reservar para esta línea
            reservas_actuales = ReservaStock.objects.filter(
                id_orden_venta_producto=linea,
                id_estado_reserva=estado_reserva_activa
            ).aggregate(total=Sum('cantidad_reservada'))['total'] or 0
            
            cantidad_pendiente_reserva = linea.cantidad - reservas_actuales
            
            if cantidad_pendiente_reserva <= 0:
                continue # Ya está todo reservado
            
            # B. Verificar stock físico disponible (Lotes PT)
            stock_fisico_disponible = get_stock_disponible_para_producto(linea.id_producto.id_producto)
            
            if stock_fisico_disponible >= cantidad_pendiente_reserva:
                # C. Reservar lo que falta
                _reservar_stock_pt(linea, cantidad_pendiente_reserva, estado_reserva_activa)
            else:
                print(f"     ⚠️ ALERTA: Stock insuficiente para OV {ov.id_orden_venta}, Prod: {linea.id_producto.nombre}. (Faltan {cantidad_pendiente_reserva})")
                todas_lineas_listas = False
                break # Cortamos el proceso de esta OV, no se puede pasar de estado
        
        # D. Si todas las líneas tienen su reserva completa, cambiamos estado
        if todas_lineas_listas:
            ov.id_estado_venta = estado_ov_pendiente_pago
            ov.save(update_fields=['id_estado_venta'])
            print(f"     ✅ OV {ov.id_orden_venta} actualizada a 'Pendiente de Pago'. Stock reservado.")
        else:
            print(f"     ❌ OV {ov.id_orden_venta} no pudo cambiar de estado (falta stock).")


    # ===================================================================
    # 🆕 PASO 0.5: LIMPIEZA DE RESERVAS DE OVs CANCELADAS
    # (Liberar stock PT retenido por ventas que se cancelaron)
    # ===================================================================
    print(f"\n[PASO 0.5] Liberando stock de Órdenes de Venta canceladas...")

    # 1. Buscar el estado "Cancelada" (ajusta el string si tu estado se llama diferente, ej: "Anulada")
    try:
        estado_ov_cancelada = EstadoVenta.objects.get(descripcion__icontains="Cancelada")
        
        # 2. Borrar todas las reservas de stock asociadas a OVs en ese estado
        #    Filtramos: Reserva -> LineaOV -> OV -> Estado
        reservas_a_liberar = ReservaStock.objects.filter(
            id_orden_venta_producto__id_orden_venta__id_estado_venta=estado_ov_cancelada
        )
        
        cantidad_reservas = reservas_a_liberar.count()
        
        if cantidad_reservas > 0:
            reservas_a_liberar.delete()
            print(f"   ✅ Se liberaron {cantidad_reservas} reservas de stock. Ahora están disponibles para otras OVs.")
        else:
            print("   > No hay reservas retenidas por OVs canceladas.")
            
    except EstadoVenta.DoesNotExist:
        print("   ⚠️ No se encontró el estado 'Cancelada' en la BD. Saltando limpieza.")
        
    # ===================================================================
    # PASO 1-3: JIT Y LÍNEAS PENDIENTES
    # ===================================================================
    print("\n[PASO 1-3/6] Identificando demandas netas y JIT...")

    estados_ov_activos = [estado_ov_creada, estado_ov_en_preparacion]
    
    lineas_ov_pendientes = OrdenVentaProducto.objects.filter(
        id_orden_venta__id_estado_venta__in=estados_ov_activos,
        id_orden_venta__fecha_entrega__range=[hoy, fecha_limite_ov],
        ops_vinculadas__isnull=True
    ).select_related(
        'id_orden_venta', 'id_producto'
    ).order_by('id_orden_venta__fecha_entrega', 'id_orden_venta__id_prioridad__id_prioridad')

    stock_virtual_pt = {
        p_id: get_stock_disponible_para_producto(p_id)
        for p_id in lineas_ov_pendientes.values_list('id_producto_id', flat=True).distinct()
    }

    lineas_para_producir = [] 

    for linea_ov in lineas_ov_pendientes:
        ov = linea_ov.id_orden_venta
        producto_id = linea_ov.id_producto_id
        
        cantidad_faltante_a_reservar = linea_ov.cantidad 
        stock_disp = stock_virtual_pt.get(producto_id, 0)
        
        tomar_de_stock = min(stock_disp, cantidad_faltante_a_reservar)
        cantidad_para_producir = cantidad_faltante_a_reservar - tomar_de_stock

        if tomar_de_stock > 0:
            stock_virtual_pt[producto_id] -= tomar_de_stock
            if ov.fecha_entrega.date() == tomorrow:
                print(f"   > Reservando JIT: {tomar_de_stock} de {linea_ov.id_producto.nombre} para OV {ov.id_orden_venta}")
                _reservar_stock_pt(linea_ov, tomar_de_stock, estado_reserva_activa)
            else:
                _reservar_stock_pt(linea_ov, tomar_de_stock, estado_reserva_activa)

        if cantidad_para_producir > 0:
            print(f"   > OV {ov.id_orden_venta} (Línea {linea_ov.id_orden_venta_producto}) necesita PRODUCIR {cantidad_para_producir} de {linea_ov.id_producto.nombre}")
            lineas_para_producir.append((linea_ov, cantidad_para_producir))
            if ov.id_estado_venta != estado_ov_en_preparacion:
                ov.id_estado_venta = estado_ov_en_preparacion
                ov.save(update_fields=['id_estado_venta'])
        
        elif tomar_de_stock >= linea_ov.cantidad:
             pass


    # ===================================================================
    # ❗️ PASO 4: CANCELACIÓN DE OPs HUÉRFANAS
    # ===================================================================
    """
    print(f"\n[PASO 4/6] Verificando OPs 'En espera' huérfanas (OVs canceladas)...")

    ov_activas_ids = set(OrdenVenta.objects.filter(
        id_estado_venta__in=estados_ov_activos
    ).values_list('id_orden_venta', flat=True))

    ops_en_espera = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_op_en_espera
    ).prefetch_related('ovs_vinculadas__id_orden_venta_producto__id_orden_venta') 

    ops_a_cancelar = []

  
        for op in ops_en_espera:
            ovs_vinculadas_activas = False
            for peg in op.ovs_vinculadas.all():
                if peg.id_orden_venta_producto.id_orden_venta_id in ov_activas_ids:
                    ovs_vinculadas_activas = True
                    break 
            
            if not ovs_vinculadas_activas:
                ops_a_cancelar.append(op.id_orden_produccion)
                print(f"   > OP {op.id_orden_produccion} está huérfana (OV cancelada/entregada). Marcando para cancelar.")


             # --- De aquí para abajo es solo para las AUTOMÁTICAS ---
        
            ovs_vinculadas_activas = False
            for peg in op.ovs_vinculadas.all():
                if peg.id_orden_venta_producto.id_orden_venta_id in ov_activas_ids:
                    ovs_vinculadas_activas = True
                    break
    """

    # ===================================================================
    # ❗️ PASO 4: CANCELACIÓN DE OPs HUÉRFANAS Y LIBERACIÓN DE MP
    # ===================================================================
    print(f"\n[PASO 4/6] Verificando OPs 'En espera' huérfanas (OVs canceladas)...")

    ov_activas_ids = set(OrdenVenta.objects.filter(
        id_estado_venta__in=estados_ov_activos
    ).values_list('id_orden_venta', flat=True))

    ops_en_espera = OrdenProduccion.objects.filter(
        id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio]
    ).prefetch_related(
        'ovs_vinculadas__id_orden_venta_producto__id_orden_venta',
        'reservamateriaprima_set' # ❗️ Asegurate que el related_name sea correcto, sino usa reserva_materia_prima_set
    ) 

    ops_a_cancelar_objs = [] # Guardamos los objetos, no solo IDs

    for op in ops_en_espera:
        
        # 1. Si es MANUAL, la ignoramos (no se cancela)
        # (Asumiendo que ya agregaste el campo es_generada_automaticamente)
        if getattr(op, 'es_generada_automaticamente', False) is False:
             print(f"   > OP {op.id_orden_produccion} es MANUAL. Se conserva.")
             continue

        # 2. Verificar vinculaciones
        ovs_vinculadas_activas = False
        for peg in op.ovs_vinculadas.all():
            if peg.id_orden_venta_producto.id_orden_venta_id in ov_activas_ids:
                ovs_vinculadas_activas = True
                break 
        
        if not ovs_vinculadas_activas:
            ops_a_cancelar_objs.append(op)
            print(f"   > OP {op.id_orden_produccion} es HUÉRFANA. Marcando para cancelar.")

    # PROCESO DE CANCELACIÓN Y DEVOLUCIÓN DE STOCK A MEMORIA
    if ops_a_cancelar_objs:
        print(f"   > Cancelando {len(ops_a_cancelar_objs)} OPs y liberando sus materiales...")
        
        for op_cancelar in ops_a_cancelar_objs:
            
            # A. Recuperar reservas de MP antes de borrarlas
            # ❗️ Ajusta 'reserva_materia_prima_set' si tu related_name es diferente en el modelo ReservaMateriaPrima
            reservas_mp = ReservaMateriaPrima.objects.filter(id_orden_produccion=op_cancelar)
            
            for reserva in reservas_mp:
                mp_id = reserva.id_lote_materia_prima.id_materia_prima_id
                cantidad_liberada = reserva.cantidad_reservada
                
                # B. DEVOLVER AL POOL VIRTUAL (Para que el Paso 5 la use)
                if mp_id in stock_virtual_mp:
                    stock_virtual_mp[mp_id] += cantidad_liberada
                    print(f"     ♻️ Liberados {cantidad_liberada} de MP {mp_id} (Vuelven al pool virtual).")
                else:
                    # Si no estaba en el pool (raro), lo inicializamos
                    stock_virtual_mp[mp_id] = cantidad_liberada

            # C. Borrar datos físicos
            reservas_mp.delete() # Borra las reservas de MP
            CalendarioProduccion.objects.filter(id_orden_produccion=op_cancelar).delete() # Borra calendario
            
            # D. Marcar OP como cancelada
            op_cancelar.id_estado_orden_produccion = estado_op_cancelada
            op_cancelar.save()


    # ===================================================================
    # 🆕 PASO 4.5: REASIGNACIÓN DE STOCK A OPs "EN ESPERA"
    # (Prioridad: Las OPs viejas comen antes que las nuevas)
    # ===================================================================
    print(f"\n[PASO 4.5] Intentando asignar stock liberado a OPs antiguas en espera...")

    # 1. Buscamos OPs que siguen esperando material
    # Ordenamos por fecha para respetar FIFO (primero entra, primero se sirve)
    ops_remanentes = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_op_en_espera
    ).order_by('fecha_planificada')

    for op in ops_remanentes:
        print(f"   > Re-evaluando OP {op.id_orden_produccion} (Producto: {op.id_producto.nombre})...")
        
        try:
            receta = Receta.objects.get(id_producto=op.id_producto)
            ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
            
            op_completo = True # Asumimos que sí, hasta que falte algo
            
            for ing in ingredientes:
                mp_id = ing.id_materia_prima_id
                
                # A. Calcular cuánto necesita TOTAL
                cantidad_total_necesaria = ing.cantidad * op.cantidad
                
                # B. Calcular cuánto YA tiene reservado (de ejecuciones anteriores)
                reservado_actual = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=op,
                    id_lote_materia_prima__id_materia_prima_id=mp_id
                ).aggregate(total=Sum('cantidad_reservada'))['total'] or 0
                
                cantidad_faltante = cantidad_total_necesaria - reservado_actual
                
                if cantidad_faltante <= 0:
                    continue # Este ingrediente está cubierto
                
                # C. Intentar tomar del Stock Virtual (que incluye lo liberado en Paso 4)
                stock_disp_virtual = stock_virtual_mp.get(mp_id, 0)
                
                tomar_ahora = min(stock_disp_virtual, cantidad_faltante)
                
                if tomar_ahora > 0:
                    # 1. Descontar del virtual
                    stock_virtual_mp[mp_id] -= tomar_ahora
                    
                    # 2. Crear la reserva física REAL en BD
                    #    (Usamos stock REAL para buscar el lote, porque si está en virtual es que está en físico)
                    stock_real_mp = get_stock_disponible_para_materia_prima(mp_id) 
                    cant_a_reservar_bd = min(stock_real_mp, tomar_ahora) # Safety check
                    
                    if cant_a_reservar_bd > 0:
                        _reservar_stock_mp(op, mp_id, cant_a_reservar_bd, estado_reserva_mp_activa)
                        print(f"     ✅ Asignados {cant_a_reservar_bd} de MP {mp_id} a OP {op.id_orden_produccion} (Recuperado).")
                    
                    # Recalcular faltante
                    cantidad_faltante -= tomar_ahora

                if cantidad_faltante > 0:
                    op_completo = False # Todavía le falta, no puede iniciar
            
            # D. Si consiguió TODO, actualizamos estado
            if op_completo:
                op.id_estado_orden_produccion = estado_op_pendiente_inicio
                op.save()
                print(f"     🎉 ¡OP {op.id_orden_produccion} completó sus materiales! Pasa a 'Pendiente de inicio'.")
                
        except Receta.DoesNotExist:
            print(f"     ⚠️ La OP {op.id_orden_produccion} no tiene receta activa.")


    # ===================================================================
    # ❗️ PASO 5: SCHEDULING (MTO) Y CÁLCULO DE MP Y OCs
    # (Lógica de MP/OC movida ANTES del Calendar Walk)
    # ===================================================================
    print(f"\n[PASO 5/6] Planificando OPs (MTO) para {len(lineas_para_producir)} nuevas líneas de OV...")

    for linea_ov, cantidad_a_producir in lineas_para_producir:
        
        producto = linea_ov.id_producto
        ov = linea_ov.id_orden_venta
        fecha_entrega_ov = ov.fecha_entrega.date()
        
        print(f"   --- Planificando para OV {ov.id_orden_venta} (Línea {linea_ov.id_orden_venta_producto}) ---")

        try:
            # --- A. CÁLCULO DE TIEMPO DE PRODUCCIÓN ---
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
            
            horas_necesarias_float = float(cantidad_a_producir) / float(cant_total_por_hora)
            horas_necesarias_totales = math.ceil(horas_necesarias_float)
            dias_produccion_estimados = math.ceil(horas_necesarias_totales / HORAS_LABORABLES_POR_DIA)
            
            print(f"      > Necesita {horas_necesarias_float:.2f} horas-máquina (redondeado a {horas_necesarias_totales}hs enteras).")

            # --- B. CÁLCULO DE FECHA IDEAL DE INICIO (POR OV) ---
            fecha_planificada_ideal = fecha_entrega_ov - timedelta(days=dias_produccion_estimados) - timedelta(DIAS_BUFFER_ENTREGA_PT)
            if fecha_planificada_ideal < hoy:
                fecha_planificada_ideal = hoy

            # --- ❗️ C. CHEQUEO DE MP Y CÁLCULO DE LEAD TIME (NUEVO) ---
            print(f"      > [PASO 5C] Calculando MP y Lead Time...")
            receta = Receta.objects.get(id_producto=producto)
            ingredientes_totales = RecetaMateriaPrima.objects.filter(id_receta=receta)
            max_lead_time_mp = 0
            op_tiene_todo_el_material_EN_STOCK = True
            
            # ❗️ Creamos la OP aquí (temporal) para poder usarla en _reservar_stock_mp
            op = OrdenProduccion(
                id_producto=producto,
                id_estado_orden_produccion=estado_op_en_espera,
                cantidad=cantidad_a_producir,
                es_generada_automaticamente=True
            )
            # ❗️ NOTA: No la guardamos hasta tener la fecha real

            for ingr in ingredientes_totales:
                mp_id = ingr.id_materia_prima_id
                mp = ingr.id_materia_prima
                cantidad_requerida_op = ingr.cantidad * op.cantidad
                cantidad_faltante_op = cantidad_requerida_op

                stock_mp_disponible = stock_virtual_mp.get(mp_id, 0)
                tomar_de_stock = min(stock_mp_disponible, cantidad_faltante_op)
                
                if tomar_de_stock > 0:
                    # Reservamos del pool global (no creamos el objeto de BBDD aún)
                    stock_virtual_mp[mp_id] -= tomar_de_stock
                    cantidad_faltante_op -= tomar_de_stock
                
                if cantidad_faltante_op <= 0: continue
                op_tiene_todo_el_material_EN_STOCK = False
                
                stock_oc_disponible = stock_virtual_oc.get(mp_id, 0)
                tomar_de_oc = min(stock_oc_disponible, cantidad_faltante_op)
                
                if tomar_de_oc > 0:
                    stock_virtual_oc[mp_id] -= tomar_de_oc
                    cantidad_faltante_op -= tomar_de_oc
                
                if cantidad_faltante_op <= 0: continue
                
                cantidad_a_comprar = cantidad_faltante_op
                if cantidad_a_comprar > 0:
                    lead_proveedor = ingr.id_materia_prima.id_proveedor.lead_time_days
                    max_lead_time_mp = max(max_lead_time_mp, lead_proveedor)
                    
                    # Agregamos la compra al pool global
                    print(f"      ! Faltan {cantidad_a_comprar} de {mp.nombre}. Agregando a OC.")
                    proveedor = mp.id_proveedor
                    compra_agregada = compras_agregadas_por_proveedor[proveedor.id_proveedor]
                    compra_agregada["proveedor"] = proveedor
                    compra_agregada["items"][mp_id] += cantidad_a_comprar
                    
                    # (La 'fecha_requerida_mas_temprana' se calculará en PASO 6)
            
            # --- ❗️ D. CALCULAR FECHA DE INICIO MÍNIMA REAL ---
            
            # La MP llegará (como muy pronto)
            fecha_llegada_mp_estimada = hoy + timedelta(days=max_lead_time_mp + DIAS_BUFFER_RECEPCION_MP)
            
            # La fecha MÍNIMA para empezar es la MÁS TARDÍA de:
            # 1. La fecha ideal por la OV (calculada en B)
            # 2. La fecha en que llega la MP
            fecha_inicio_minima_real = max(fecha_planificada_ideal, fecha_llegada_mp_estimada)
            
            print(f"      > Fecha ideal (OV): {fecha_planificada_ideal}. Fecha llegada MP: {fecha_llegada_mp_estimada}.")
            print(f"      > Inicio MÍNIMO REAL (max): {fecha_inicio_minima_real}.")


           # --- E. LÓGICA "WALK THE CALENDAR" ---
            
            # ❗️ 1. Variable para rastrear la cantidad restante de la OP
            cantidad_pendiente_op = cantidad_a_producir 
            
            horas_pendientes = horas_necesarias_totales 
            fecha_a_buscar = fecha_inicio_minima_real

            while fecha_a_buscar.weekday() >= 5: # 5=Sábado, 6=Domingo
                fecha_a_buscar += timedelta(days=1)

            fecha_inicio_real_asignada = None
            fecha_fin_real_asignada = None
            reservas_a_crear_bulk = []
            
            print(f"       > Buscando hueco desde {fecha_a_buscar}...")

            # ❗️ 2. El bucle ahora TAMBIÉN debe chequear la cantidad
            while horas_pendientes > 0 and cantidad_pendiente_op > 0:
                horas_libres_cuello_botella = HORAS_LABORABLES_POR_DIA
                lineas_ids_producto = [c.id_linea_produccion_id for c in capacidades_linea]
                
                # ... (Lógica de carga_existente no cambia) ...
                carga_existente = CalendarioProduccion.objects.filter(
                    id_linea_produccion_id__in=lineas_ids_producto,
                    fecha=fecha_a_buscar,
                    id_orden_produccion__id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio]
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

                horas_libres_enteras = math.floor(horas_libres_cuello_botella)

                if horas_libres_enteras <= 0:
                    fecha_a_buscar += timedelta(days=1)
                    continue
                    
                horas_a_reservar_hoy = min(horas_pendientes, horas_libres_enteras) 

                se_reservo_tiempo_en_fecha = False

                for cap_linea in capacidades_linea:
                    
                    # ❗️ 3. Calcular la cantidad MÁXIMA que esta línea puede hacer
                    # Ej: (2 horas * 75/hr) = 150
                    cantidad_calculada_linea = round(float(horas_a_reservar_hoy) * float(cap_linea.cant_por_hora))
                    
                    # ❗️ 4. LIMITAR esa cantidad a lo que realmente falta
                    # Ej: min(100, 150) = 100
                    cantidad_real_linea = min(cantidad_pendiente_op, cantidad_calculada_linea)

                    if horas_a_reservar_hoy > 0 and cantidad_real_linea > 0:
                        se_reservo_tiempo_en_fecha = True 
                        
                        # ❗️ 5. CORRECCIÓN: Usar el bloque de horas entero (horas_a_reservar_hoy)
                        # NO calcular 'horas_reales_linea'.
                        
                        reservas_a_crear_bulk.append(
                            CalendarioProduccion(
                                id_orden_produccion=op, 
                                id_linea_produccion=cap_linea.id_linea_produccion,
                                fecha=fecha_a_buscar,
                                horas_reservadas=horas_a_reservar_hoy, # ❗️ USAR EL BLOQUE TOTAL (Ej: 2)
                                cantidad_a_producir=cantidad_real_linea # ❗️ USAR CANTIDAD REAL (Ej: 100)
                            )
                        )
                        
                        # ❗️ 6. RESTAR de la cantidad pendiente
                        cantidad_pendiente_op -= cantidad_real_linea
                        
                        # ❗️ Si esta línea ya completa la OP, no asignar más líneas
                        if cantidad_pendiente_op <= 0:
                            break 
                
                # --- Fuera del bucle for cap_linea ---

                if se_reservo_tiempo_en_fecha:
                    horas_pendientes -= horas_a_reservar_hoy 
                
                    if fecha_inicio_real_asignada is None:
                        fecha_inicio_real_asignada = fecha_a_buscar
                    
                    print(f"       > Reservadas {horas_a_reservar_hoy}hs enteras en {fecha_a_buscar}. Faltan {horas_pendientes}hs. Quedan {cantidad_pendiente_op} unidades.")
                
                if cantidad_pendiente_op <= 0:
                    horas_pendientes = 0 # Forzar salida del while
                    
                if (horas_pendientes > 0) or (not se_reservo_tiempo_en_fecha):
                    fecha_a_buscar += timedelta(days=1)
                
                while fecha_a_buscar.weekday() >= 5:
                        fecha_a_buscar += timedelta(days=1)

                # Reseteamos lógica de horas si cambiamos de día y aún falta cantidad
                if cantidad_pendiente_op > 0:
                    horas_pendientes = horas_necesarias_totales

                elif se_reservo_tiempo_en_fecha:
                     # Avanzamos un día
                     fecha_a_buscar += timedelta(days=1)

                    # ✅ MODIFICACIÓN 3: Aquí también, saltar fines de semana
                     while fecha_a_buscar.weekday() >= 5:
                        fecha_a_buscar += timedelta(days=1)


            # --- Fuera del bucle while ---
            if fecha_inicio_real_asignada is None:
                fecha_inicio_real_asignada = fecha_inicio_minima_real
            
            fecha_fin_real_asignada = fecha_a_buscar - timedelta(days=1)
            
            # Asegurarse que la fecha de fin no sea anterior a la de inicio
            if fecha_fin_real_asignada < fecha_inicio_real_asignada:
                fecha_fin_real_asignada = fecha_inicio_real_asignada

            # --- F. GUARDAR OP, PEGGING Y RESERVAS DE CALENDARIO ---
            
            # Ahora guardamos la OP con sus fechas reales
            op.fecha_planificada = timezone.make_aware(datetime.combine(fecha_inicio_real_asignada, datetime.min.time()))
            op.fecha_fin_planificada = fecha_fin_real_asignada
            op.save() # ❗️ Guardamos la OP (obtiene PK)
            
            print(f"      > CREADA OP {op.id_orden_produccion} (MTO) y vinculada a OV {ov.id_orden_venta}.")
            
            # Vinculamos el Pegging (ahora la OP tiene PK)
            OrdenProduccionPegging.objects.create(
                id_orden_produccion=op,
                id_orden_venta_producto=linea_ov,
                cantidad_asignada=cantidad_a_producir
            )
            
            # Asignamos la OP (con PK) a las reservas y las creamos
            for reserva in reservas_a_crear_bulk:
                reserva.id_orden_produccion = op
            CalendarioProduccion.objects.bulk_create(reservas_a_crear_bulk)
            
            print(f"      -> PLANIFICACIÓN REAL: {op.fecha_planificada.date()} a {op.fecha_fin_planificada}.")

           # 1. Calculamos la nueva fecha sugerida (Fin Producción + Buffer + 1 día seguridad)
            dias_totales_margen = DIAS_BUFFER_ENTREGA_PT + 1
            nueva_fecha_entrega_sugerida_date = op.fecha_fin_planificada + timedelta(days=dias_totales_margen)

            while nueva_fecha_entrega_sugerida_date.weekday() >= 5:
                nueva_fecha_entrega_sugerida_date += timedelta(days=1)

            # 2. Verificamos si hay retraso (Si la nueva fecha es MAYOR a la original)
            if nueva_fecha_entrega_sugerida_date > ov.fecha_entrega.date():
                
                print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print(f"      !!! ALERTA DE ENTREGA: OP {op.id_orden_produccion}")
                print(f"      !!! Vinculada a: OV {ov.id_orden_venta} (Entrega actual: {ov.fecha_entrega.date()})")
                print(f"      !!! Producción termina el: {op.fecha_fin_planificada}")
                print(f"      !!! Nueva fecha de entrega sugerida: {nueva_fecha_entrega_sugerida_date}")
                print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                print(f"      !!! DESPLAZANDO OV {ov.id_orden_venta} a {nueva_fecha_entrega_sugerida_date}")
                
                # ✅ SOLUCIÓN: Asignación DIRECTA.
                # 'nueva_fecha_entrega_sugerida_date' ya es un objeto 'date' válido.
                # No hace falta convertirlo a datetime ni agregar timezone.
                # Django se encarga del resto.
                
                ov.fecha_entrega = nueva_fecha_entrega_sugerida_date
                ov.id_estado_venta = estado_ov_en_preparacion 
                
                # Guardamos solo los campos modificados
                ov.save(update_fields=['fecha_entrega', 'id_estado_venta'])

            # --- H. LÓGICA DE LOTE ---
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
            except EstadoLoteProduccion.DoesNotExist:
                print(f"      !ERROR CRÍTICO: No se pudo crear Lote. Estado 'En espera' no existe.")

            # --- I. (PASO 5) ACTUALIZAR ESTADO Y RESERVAS DE MP ---
            print(f"      > [PASO 5I] Creando Reservas de MP y asignando Estado...")
            
            # Volvemos a iterar, esta vez para crear las Reservas de MP (ahora que OP tiene PK)
            for ingr in ingredientes_totales:
                mp_id = ingr.id_materia_prima_id
                cantidad_requerida_op = ingr.cantidad * op.cantidad
                cantidad_faltante_op = cantidad_requerida_op

                # Usamos el pool global (que ya descontamos virtualmente)
                stock_mp_disponible_real = get_stock_disponible_para_materia_prima(mp_id)
                
                # Cuánto debemos tomar del stock real (no del virtual)
                tomar_de_stock = min(stock_mp_disponible_real, cantidad_faltante_op)
                
                if tomar_de_stock > 0:
                    _reservar_stock_mp(op, mp_id, tomar_de_stock, estado_reserva_mp_activa)

            if op_tiene_todo_el_material_EN_STOCK:
                op.id_estado_orden_produccion = estado_op_pendiente_inicio
                print(f"      > OP {op.id_orden_produccion} tiene toda la MP en Stock. Estado -> Pendiente de inicio")
            else:
                op.id_estado_orden_produccion = estado_op_en_espera
                print(f"      > OP {op.id_orden_produccion} esperando MP (en tránsito o por comprar). Estado -> En espera")

            fecha_inicio_op = op.fecha_planificada.date() - timedelta(days=max_lead_time_mp + DIAS_BUFFER_RECEPCION_MP)
            op.fecha_inicio = timezone.make_aware(datetime.combine(fecha_inicio_op, datetime.min.time()))
            
            # Guardamos todo al final
            op.save()

        except Receta.DoesNotExist:
            print(f"      !ERROR: {producto.nombre} no tiene Receta. Omitiendo OP.")
            if op and op.pk: op.delete()
        except Exception as e:
            print(f"      !ERROR al planificar OP para {producto.nombre}: {e}")
            if op and op.pk: op.delete()
            
    # ===================================================================
    # ❗️ PASO 6: CREACIÓN DE OCs (AGREGADAS)
    # ===================================================================
    print(f"\n[PASO 6/6] Creando {len(compras_agregadas_por_proveedor)} OCs agrupadas por proveedor...")

    # (La lógica de este paso no cambia, solo lee el diccionario
    # 'compras_agregadas_por_proveedor' que llenamos en el PASO 5C)
    
    for proveedor_id, info in compras_agregadas_por_proveedor.items():
        proveedor = info["proveedor"]
        # ❗️ Calculamos la fecha de necesidad más temprana AHORA
        fecha_requerida_mas_temprana = date(9999, 12, 31)
        for mp_id in info["items"].keys():
            # Buscamos la fecha más temprana para esta MP en las OPs 'En espera'
            ops_necesitadas = OrdenProduccion.objects.filter(
                id_estado_orden_produccion=estado_op_en_espera,
                id_producto__receta__recetamateriaprima__id_materia_prima_id=mp_id
            ).order_by('fecha_planificada')
            
            op_mas_temprana = ops_necesitadas.first()
            if op_mas_temprana:
                fecha_req_op = op_mas_temprana.fecha_planificada.date() - timedelta(days=DIAS_BUFFER_RECEPCION_MP)
                if fecha_req_op < fecha_requerida_mas_temprana:
                    fecha_requerida_mas_temprana = fecha_req_op
        
        if fecha_requerida_mas_temprana == date(9999, 12, 31):
            fecha_requerida_mas_temprana = hoy # Fallback
            
        fecha_necesaria_mp = fecha_requerida_mas_temprana
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
                    # ✅ CORRECCIÓN AQUÍ: SUMAR en lugar de SO-BRESCRIBIR
                    cantidad_anterior = item_oc.cantidad
                    item_oc.cantidad += cantidad_necesaria_hoy 
                    item_oc.save()
                    
                    print(f"      - Item existente (MP {mp_id}) en OC {oc.id_orden_compra} AUMENTADO de {cantidad_anterior} a {item_oc.cantidad}.")

    print("\n--- PLANIFICADOR MRP FINALIZADO ---")