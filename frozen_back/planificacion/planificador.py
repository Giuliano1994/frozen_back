

import math
from datetime import timedelta, date, datetime
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, F
from django.db.models.functions import Coalesce
from collections import defaultdict

# --- Importar Modelos de todas las apps ---
from ventas.models import OrdenVenta, OrdenVentaProducto, EstadoVenta
from productos.models import Producto
from produccion.models import OrdenProduccion, EstadoOrdenProduccion
from compras.models import OrdenCompra, OrdenCompraMateriaPrima, EstadoOrdenCompra
from stock.models import (
    LoteProduccion, LoteMateriaPrima, EstadoLoteProduccion, 
    EstadoLoteMateriaPrima, ReservaStock, ReservaMateriaPrima, 
    EstadoReserva, EstadoReservaMateria
)
# --- IMPORTAR SERVICIOS DE STOCK (Clave) ---
from stock.services import get_stock_disponible_para_producto, get_stock_disponible_para_materia_prima
from recetas.models import ProductoLinea, Receta, RecetaMateriaPrima
from materias_primas.models import MateriaPrima, Proveedor

# --- Constantes de Planificación (Centralizadas) ---
HORAS_LABORABLES_POR_DIA = 8
DIAS_BUFFER_ENTREGA_PT = 1      # Terminar producción X días ANTES de la entrega de la OV
DIAS_BUFFER_RECEPCION_MP = 1 # Recibir MP X días ANTES de iniciar la OP

# ===================================================================
# FUNCIONES HELPER
# (Las funciones _reservar_stock_pt y _reservar_stock_mp 
#  son las mismas que ya corregimos, no es necesario copiarlas de nuevo)
# ===================================================================

# --- REEMPLAZA ESTA FUNCIÓN COMPLETA ---
@transaction.atomic
def _reservar_stock_pt(linea_ov: OrdenVentaProducto, cantidad_a_reservar: int, estado_activa: EstadoReserva):
    """
    Intenta reservar stock de PT para una línea de venta, usando FIFO (FEFO).
    
    --- VERSIÓN CORREGIDA ---
    Calcula el disponible usando 'annotate' en lugar de la property del modelo
    para asegurar que la lógica sea idéntica a 'get_stock_disponible_para_producto'.
    """
    
    # 1. Filtro para reservas activas (copiado de 'stock.services')
    filtro_reservas_activas = Q(reservas__id_estado_reserva__descripcion='Activa')

    # 2. Buscamos lotes y calculamos su disponible real en la BD (copiado de 'stock.services')
    lotes_disponibles = LoteProduccion.objects.filter(
        id_producto=linea_ov.id_producto,
        id_estado_lote_produccion__descripcion="Disponible" # Usar minúscula
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    ).annotate(
        disponible=F('cantidad') - F('total_reservado') # 'disponible' es ahora un campo anotado
    ).filter(
        disponible__gt=0 # Solo lotes que REALMENTE tengan stock
    ).order_by('fecha_vencimiento')

    cantidad_pendiente = cantidad_a_reservar
    for lote in lotes_disponibles:
        if cantidad_pendiente <= 0:
            break
        
        # 3. Usamos el campo 'disponible' anotado, no la property
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
            
    print(f"    > (OV {linea_ov.id_orden_venta_id}) Reservados {cantidad_a_reservar - cantidad_pendiente} de {cantidad_a_reservar} de {linea_ov.id_producto.nombre}")
# --- FIN DE LA FUNCIÓN REEMPLAZADA ---

@transaction.atomic
def _reservar_stock_mp(op: OrdenProduccion, mp_id: int, cantidad_a_reservar: int, estado_activa: EstadoReservaMateria):
    # ... (Tu código helper de reservar MP (con annotate) va aquí) ...
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
    print(f"    > (OP {op.id_orden_produccion}) Reservados {cantidad_a_reservar - cantidad_pendiente} de {cantidad_a_reservar} de MP {mp_id}")


# ===================================================================
# FUNCIÓN PRINCIPAL DEL PLANIFICADOR
# ===================================================================

@transaction.atomic
def ejecutar_planificacion_diaria_mrp(fecha_simulada: date):
    """
    Ejecuta el proceso completo de MRP Híbrido (JIT + Planificación).
    Sigue la lógica de 6 pasos definida por el usuario.
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
    
    demanda_neta_produccion = defaultdict(lambda: {
        "cantidad": 0, 
        "fecha_mas_temprana": date(9999, 12, 31),
        "umbral_minimo": 0
    })
    
    reservas_jit_para_manana = {}
    ordenes_para_actualizar_estado = {}

    for ov in ordenes_semana:
        print(f"  Analizando OV {ov.id_orden_venta} (Entrega: {ov.fecha_entrega.date()})...")
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
                    print(f"    > (OV {ov.id_orden_venta}) Stock de {producto.nombre} encontrado, pero no se reserva (Entrega: {ov.fecha_entrega.date()})")

            if cantidad_para_producir > 0:
                orden_esta_completa = False
                demanda_neta = demanda_neta_produccion[producto_id]
                demanda_neta["cantidad"] += cantidad_para_producir
                demanda_neta["umbral_minimo"] = producto.umbral_minimo
                if ov.fecha_entrega.date() < demanda_neta["fecha_mas_temprana"]:
                    demanda_neta["fecha_mas_temprana"] = ov.fecha_entrega.date()

        if orden_esta_completa:
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
            print(f"  > Reservando JIT: {cantidad} de {linea_a_reservar.id_producto.nombre} para OV {linea_a_reservar.id_orden_venta_id}")
            _reservar_stock_pt(linea_a_reservar, cantidad, estado_reserva_activa)
        except OrdenVentaProducto.DoesNotExist:
            print(f"  !ERROR: No se encontró la línea de OV {linea_ov_id} para reservar.")
            
    for ov_id, estado in ordenes_para_actualizar_estado.items():
        OrdenVenta.objects.filter(pk=ov_id).update(id_estado_venta=estado)

    # ===================================================================
    # PASO 4: NETTING Y CREACIÓN DE ÓRDENES DE PRODUCCIÓN (Req 4)
    # ===================================================================
    print(f"\n[PASO 4/6] Netting (Balance) y Creación de OPs...")
    
    # ops_a_procesar_en_paso_5 contendrá: (op_creada, dict_faltante_mp)
    ops_a_procesar_en_paso_5 = []
    
    # --- INICIO DE CORRECCIÓN ---
    # Obtenemos TODOS los productos que tienen demanda O producción en curso
    productos_en_produccion_ids = OrdenProduccion.objects.filter(
        # La oferta son TODAS las OPs que no están terminadas ni canceladas
        id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio, estado_op_en_proceso]
    ).values_list('id_producto_id', flat=True)
    
    todos_los_productos_ids = set(demanda_neta_produccion.keys()) | set(productos_en_produccion_ids)
    print(f"  > Analizando {len(todos_los_productos_ids)} productos para netting de producción...")

    for producto_id in todos_los_productos_ids:
        producto = Producto.objects.get(pk=producto_id)
        
        # 1. ¿CUÁNTO NECESITAMOS? (Demanda Neta de PT del PASO 1 + Stock Mínimo)
        info_demanda = demanda_neta_produccion.get(producto_id, {})
        cantidad_faltante_demanda = info_demanda.get('cantidad', 0)
        stock_proyectado_final = stock_virtual_pt.get(producto_id, 0)
        necesidad_stock_minimo = max(0, producto.umbral_minimo - stock_proyectado_final)
        
        necesidad_total_produccion = cantidad_faltante_demanda + necesidad_stock_minimo
        fecha_mas_temprana = info_demanda.get('fecha_mas_temprana', hoy + timedelta(days=7)) # Si es solo por stock min, planificar a 7 días

        # 2. ¿CUÁNTO TENEMOS EN PRODUCCIÓN? (Oferta de Producción)
        ops_existentes = OrdenProduccion.objects.filter(
            id_producto=producto, 
            id_estado_orden_produccion__in=[estado_op_en_espera, estado_op_pendiente_inicio, estado_op_en_proceso]
        )
        
        total_en_produccion_existente = ops_existentes.aggregate(total=Sum('cantidad'))['total'] or 0

        # 3. EL BALANCE
        balance = necesidad_total_produccion - total_en_produccion_existente
        
        print(f"  > Netting {producto.nombre}: Demanda Total={necesidad_total_produccion} - OPs en Curso={total_en_produccion_existente} = Balance={balance}")

        if balance > 0:
            # --- FALTANTE: Necesitamos crear una OP nueva ---
            print(f"    > Faltan {balance} unidades. Planificando OP...")
            
            cantidad_a_producir_total = balance
            fecha_entrega_ov = fecha_mas_temprana

            try:
                # --- LÓGICA DE LEAD TIME (Req 4b) ---
                receta = Receta.objects.get(id_producto=producto)
                ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
                
                max_lead_time_mp = 0
                demanda_neta_mp_op = {} # {mp_id: faltante}
                
                for ingr in ingredientes:
                    necesidad_mp = ingr.cantidad * cantidad_a_producir_total
                    stock_mp = get_stock_disponible_para_materia_prima(ingr.id_materia_prima_id)
                    
                    # --- CORRECCIÓN: Calcular faltante restando OCs en proceso ---
                    en_compra_total = OrdenCompraMateriaPrima.objects.filter(
                        id_materia_prima=ingr.id_materia_prima,
                        id_orden_compra__id_estado_orden_compra=estado_oc_en_proceso
                    ).aggregate(total=Sum('cantidad'))['total'] or 0
                    
                    faltante_mp = max(0, necesidad_mp - stock_mp - en_compra_total)
                    # --- FIN CORRECCIÓN ---
                    
                    if faltante_mp > 0:
                        lead_proveedor = ingr.id_materia_prima.id_proveedor.lead_time_days
                        max_lead_time_mp = max(max_lead_time_mp, lead_proveedor)
                        demanda_neta_mp_op[ingr.id_materia_prima_id] = faltante_mp
                
                producto_linea = ProductoLinea.objects.filter(id_producto=producto).first()
                if not producto_linea or not producto_linea.cant_por_hora or producto_linea.cant_por_hora <= 0:
                    print(f"    !ERROR: {producto.nombre} no tiene 'cant_por_hora'. Omitiendo OP.")
                    continue
                
                cant_por_hora = producto_linea.cant_por_hora
                tiempo_prod_horas = math.ceil(cantidad_a_producir_total / cant_por_hora)
                dias_produccion = math.ceil(tiempo_prod_horas / HORAS_LABORABLES_POR_DIA)
                
                dias_totales_previos = dias_produccion + max_lead_time_mp + DIAS_BUFFER_ENTREGA_PT + DIAS_BUFFER_RECEPCION_MP
                fecha_inicio_op = fecha_entrega_ov - timedelta(days=dias_totales_previos)

                if fecha_inicio_op < hoy:
                    print(f"    !ALERTA: OP para {producto.nombre} (requerida para {fecha_entrega_ov})")
                    print(f"    ...debería haber empezado el {fecha_inicio_op} (Lead Time total: {dias_totales_previos} días). Planificando ASAP.")
                    fecha_inicio_op = hoy + timedelta(days=1)
                
                fecha_inicio_dt = timezone.make_aware(datetime.combine(fecha_inicio_op, datetime.min.time()))
                # --- FIN LÓGICA LEAD TIME ---

                op, created = OrdenProduccion.objects.get_or_create(
                    id_producto=producto,
                    id_estado_orden_produccion=estado_op_en_espera,
                    fecha_inicio=fecha_inicio_dt,
                    defaults={'cantidad': cantidad_a_producir_total}
                )
                if created:
                    print(f"    -> CREADA OP {op.id_orden_produccion} para {cantidad_a_producir_total} de {producto.nombre} (Inicio: {fecha_inicio_op})")
                    # --- INICIO DE CORRECCIÓN: CREAR EL LOTE ASOCIADO ---
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
                        
                        # Asignamos el lote a la OP
                        op.id_lote_produccion = lote
                        op.save()
                        print(f"    -> CREADO LoteProduccion {lote.id_lote_produccion} y asignado a OP {op.id_orden_produccion}")

                    except EstadoLoteProduccion.DoesNotExist:
                        print(f"    !ERROR CRÍTICO: No se pudo crear Lote. Estado 'En espera' no existe en EstadoLoteProduccion.")
                    except Exception as e_lote:
                        print(f"    !ERROR CRÍTICO al crear Lote para OP {op.id_orden_produccion}: {e_lote}")
                    # --- FIN DE CORRECCIÓN ---
                
                else:
                    OrdenProduccion.objects.filter(pk=op.pk).update(cantidad=F('cantidad') + cantidad_a_producir_total)
                    op.refresh_from_db() 
                    print(f"    -> ACTUALIZADA OP {op.id_orden_produccion}: +{cantidad_a_producir_total} de {producto.nombre} (Total: {op.cantidad})")

                # Agregamos la OP nueva a la lista del PASO 5
                ops_a_procesar_en_paso_5.append( (op, demanda_neta_mp_op) )
                
            except Receta.DoesNotExist:
                print(f"    !ERROR: {producto.nombre} no tiene Receta. Omitiendo OP.")
            except Exception as e:
                print(f"    !ERROR al planificar OP para {producto.nombre}: {e}")

        elif balance < 0:
            # --- SOBRANTE: Necesitamos cancelar OPs ---
            cantidad_a_cancelar = abs(balance)
            print(f"  > {producto.nombre}: Demanda ({necesidad_total_produccion}) < Producción ({total_en_produccion_existente}). Sobran {cantidad_a_cancelar}. Cancelando OPs...")
            
            # Cancelamos OPs "En espera" primero (de más nueva a más vieja)
            ops_en_espera_a_cancelar = ops_existentes.filter(id_estado_orden_produccion=estado_op_en_espera).order_by('-fecha_inicio')
            
            for op in ops_en_espera_a_cancelar:
                if cantidad_a_cancelar <= 0: break
                
                if op.cantidad <= cantidad_a_cancelar:
                    op.id_estado_orden_produccion = estado_op_cancelada
                    op.save()
                    cantidad_a_cancelar -= op.cantidad
                    print(f"    -> CANCELADA OP {op.id_orden_produccion} (completa: {op.cantidad} unidades)")
                else:
                    op.cantidad -= cantidad_a_cancelar
                    op.save()
                    print(f"    -> REDUCIDA OP {op.id_orden_produccion} en {cantidad_a_cancelar} unidades. (Nueva cant: {op.cantidad})")
                    cantidad_a_cancelar = 0

            if cantidad_a_cancelar > 0:
                print(f"    !ALERTA: Aún sobran {cantidad_a_cancelar} unidades, pero no hay más OPs 'En espera' para cancelar.")
        
        # else: # balance == 0
            # No hacemos nada, el balance es correcto.

    # ===================================================================
    # PASO 5: RESERVAR MP Y CREAR ÓRDENES DE COMPRA (Req 5)
    # ===================================================================
    print(f"\n[PASO 5-6/6] Reservando MP y creando OCs...")
    
    compras_agregadas_por_proveedor = defaultdict(lambda: {
        "proveedor": None,
        "fecha_requerida_mas_temprana": date(9999, 12, 31),
        "items": defaultdict(int) # {mp_id: cantidad}
    })
    
    ops_listas_para_iniciar = [] # OPs que tienen todo su material

    # --- INICIO DE CORRECCIÓN ---
    # Analizamos TODAS las OPs "En espera" (las nuevas + las que sobrevivieron al netting)
    ops_totales_en_espera = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_op_en_espera
    ).order_by('fecha_inicio')
    
    print(f"  > Analizando MP para {ops_totales_en_espera.count()} OPs que están 'En espera'...")
    # --- FIN DE CORRECCIÓN ---
    
    # Pool de stock de MP
    mp_ids_necesarios = RecetaMateriaPrima.objects.filter(
        id_receta__id_producto__ordenproduccion__in=ops_totales_en_espera
    ).values_list('id_materia_prima_id', flat=True).distinct()
    stock_virtual_mp = {
        mp_id: get_stock_disponible_para_materia_prima(mp_id)
        for mp_id in mp_ids_necesarios
    }
    
    # --- NUEVO BLOQUE: POOL DE STOCK EN CAMINO ---
    print("  > Obteniendo pool de stock 'En Camino' (OCs en proceso)...")
    compras_en_proceso = OrdenCompraMateriaPrima.objects.filter(
        id_orden_compra__id_estado_orden_compra=estado_oc_en_proceso
    )
    stock_virtual_oc = defaultdict(int)
    for item in compras_en_proceso:
        stock_virtual_oc[item.id_materia_prima_id] += item.cantidad
    print(f"  > Pool de OCs en camino: {dict(stock_virtual_oc)}")
    # --- FIN NUEVO BLOQUE ---

    for op in ops_totales_en_espera:
        fecha_requerida_mp = op.fecha_inicio.date() - timedelta(days=DIAS_BUFFER_RECEPCION_MP)
        op_tiene_todo_el_material = True

        try:
            receta = Receta.objects.get(id_producto=op.id_producto)
            ingredientes_totales = RecetaMateriaPrima.objects.filter(id_receta=receta)
            
            for ingr in ingredientes_totales:
                mp_id = ingr.id_materia_prima_id
                mp = ingr.id_materia_prima
                proveedor = mp.id_proveedor
                
                cantidad_requerida_op = ingr.cantidad * op.cantidad
                
                reservado_activo_mp = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=op,
                    id_lote_materia_prima__id_materia_prima=mp_id,
                    id_estado_reserva_materia=estado_reserva_mp_activa
                ).aggregate(total=Sum('cantidad_reservada'))['total'] or 0

                cantidad_faltante_op = cantidad_requerida_op - reservado_activo_mp

                if cantidad_faltante_op <= 0:
                    continue
                
                # --- INICIO CORRECCIÓN: USAR LOS 3 POOLS DE STOCK ---
                # 1. Intentar tomar de stock físico
                stock_mp_disponible = stock_virtual_mp.get(mp_id, 0)
                tomar_de_stock = min(stock_mp_disponible, cantidad_faltante_op)
                
                if tomar_de_stock > 0:
                    print(f"  > Reservando {tomar_de_stock} de MP {mp_id} (stock) para OP {op.id_orden_produccion}")
                    _reservar_stock_mp(op, mp_id, tomar_de_stock, estado_reserva_mp_activa)
                    stock_virtual_mp[mp_id] -= tomar_de_stock # Reducimos el pool físico
                    cantidad_faltante_op -= tomar_de_stock # Reducimos el faltante
                
                if cantidad_faltante_op <= 0:
                    continue # El stock físico cubrió la necesidad
                    
                # 2. Intentar "reservar" de stock en camino
                stock_oc_disponible = stock_virtual_oc.get(mp_id, 0)
                tomar_de_oc = min(stock_oc_disponible, cantidad_faltante_op)
                
                if tomar_de_oc > 0:
                    # No creamos reserva, solo descontamos del pool virtual y del faltante
                    stock_virtual_oc[mp_id] -= tomar_de_oc
                    cantidad_faltante_op -= tomar_de_oc
                
                if cantidad_faltante_op <= 0:
                    op_tiene_todo_el_material = False # Aún no, pero ya está pedido
                    continue # El stock en camino cubre la necesidad
                
                # 3. Lo que queda, hay que comprarlo
                cantidad_a_comprar = cantidad_faltante_op
                
                if cantidad_a_comprar > 0:
                    op_tiene_todo_el_material = False
                    print(f"    ! Faltan {cantidad_a_comprar} de {mp.nombre} para OP {op.id_orden_produccion}. Agregando a OC.")
                    
                    compra_agregada = compras_agregadas_por_proveedor[proveedor.id_proveedor]
                    compra_agregada["proveedor"] = proveedor
                    compra_agregada["items"][mp_id] += cantidad_a_comprar
                    if fecha_requerida_mp < compra_agregada["fecha_requerida_mas_temprana"]:
                        compra_agregada["fecha_requerida_mas_temprana"] = fecha_requerida_mp
                # --- FIN CORRECCIÓN ---

        except Receta.DoesNotExist:
            print(f"  !ERROR: (Paso 5) OP {op.id_orden_produccion} sin receta.")
            continue
            
        if op_tiene_todo_el_material:
            ops_listas_para_iniciar.append(op)

    # 5.2: Crear las Órdenes de Compra (OC)
    print(f"  > Creando {len(compras_agregadas_por_proveedor)} OCs agrupadas por proveedor...")
    for proveedor_id, info in compras_agregadas_por_proveedor.items():
        proveedor = info["proveedor"]
        fecha_necesaria_mp = info["fecha_requerida_mas_temprana"]
        
        lead_time = proveedor.lead_time_days
        fecha_entrega_oc = fecha_necesaria_mp
        fecha_solicitud_oc = fecha_entrega_oc - timedelta(days=lead_time)

        if fecha_solicitud_oc < hoy:
            fecha_solicitud_oc = hoy
            fecha_entrega_oc = hoy + timedelta(days=lead_time)
            print(f"  !ALERTA OC: Pedido a {proveedor.nombre} está retrasado. Nueva entrega: {fecha_entrega_oc}")
            
        oc, created = OrdenCompra.objects.get_or_create(
            id_proveedor=proveedor,
            id_estado_orden_compra=estado_oc_en_proceso,
            fecha_entrega_estimada=fecha_entrega_oc,
            defaults={'fecha_solicitud': fecha_solicitud_oc}
        )
        print(f"  > Generando OC {oc.id_orden_compra} para {proveedor.nombre} (Entrega: {fecha_entrega_oc})")
        
        for mp_id, cantidad in info["items"].items():
            # --- INICIO DE CORRECCIÓN (IDEMPOTENCIA) ---
            # Usamos get_or_create. Si ya existe, NO HACEMOS NADA,
            # porque la cantidad necesaria (calculada hoy) es la misma que
            # se calculó ayer (y que ya está en la OC).
            item_oc, item_created = OrdenCompraMateriaPrima.objects.get_or_create(
                id_orden_compra=oc,
                id_materia_prima_id=mp_id,
                defaults={'cantidad': cantidad}
            )
            
            if item_created:
                print(f"    - NUEVO Item: {cantidad} de MP {mp_id}")
            else:
                # Si no se creó, significa que el planificador ya agregó este item
                # en una corrida anterior. No lo duplicamos.
                print(f"    - Item existente (MP {mp_id}) ya está en la OC. No se modifica.")
            # --- FIN DE CORRECCIÓN ---

    # 5.3: Actualizar OPs que SÍ tienen material a "Pendiente de inicio"
    for op in ops_listas_para_iniciar:
        op.id_estado_orden_produccion = estado_op_pendiente_inicio
        op.save()
        print(f"  > OP {op.id_orden_produccion} ({op.id_producto.nombre}) tiene toda la MP. Estado -> Pendiente de inicio")

    print("\n--- PLANIFICADOR MRP FINALIZADO ---")