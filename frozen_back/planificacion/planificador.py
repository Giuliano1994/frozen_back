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
    CalendarioProduccion, OrdenProduccionPegging # ❗️ IMPORTAR EL NUEVO MODELO
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
    
    # Diccionario para agrupar compras (Se inicializa 1 vez)
    compras_agregadas_por_proveedor = defaultdict(lambda: {
        "proveedor": None,
        "fecha_requerida_mas_temprana": date(9999, 12, 31),
        "items": defaultdict(int) 
    })
    
    
    # ===================================================================
    # PASO 1-3: JIT Y LÍNEAS PENDIENTES
    # (El antiguo PASO 1-2 y 3 combinados y simplificados)
    # ===================================================================
    print("\n[PASO 1-3/6] Identificando demandas netas y JIT...")

    # Buscamos todas las líneas de OV que aún no están vinculadas a una OP
    lineas_ov_pendientes = OrdenVentaProducto.objects.filter(
        id_orden_venta__id_estado_venta__in=[estado_ov_creada, estado_ov_en_preparacion],
        id_orden_venta__fecha_entrega__range=[hoy, fecha_limite_ov],
        ops_vinculadas__isnull=True # ❗️ USA LA NUEVA RELACIÓN
    ).select_related(
        'id_orden_venta', 'id_producto'
    ).order_by('id_orden_venta__fecha_entrega', 'id_orden_venta__id_prioridad__id_prioridad')

    # Pool de stock de PT (solo para las líneas pendientes)
    stock_virtual_pt = {
        p_id: get_stock_disponible_para_producto(p_id)
        for p_id in lineas_ov_pendientes.values_list('id_producto_id', flat=True).distinct()
    }

    lineas_para_producir = [] # Lista de (linea_ov, cantidad_para_producir)

    for linea_ov in lineas_ov_pendientes:
        ov = linea_ov.id_orden_venta
        producto_id = linea_ov.id_producto_id
        
        # 1. ¿Cuánto falta?
        # (Asumimos que si no tiene OP, no tiene reservas de PT)
        cantidad_faltante_a_reservar = linea_ov.cantidad 
        
        stock_disp = stock_virtual_pt.get(producto_id, 0)
        
        tomar_de_stock = min(stock_disp, cantidad_faltante_a_reservar)
        cantidad_para_producir = cantidad_faltante_a_reservar - tomar_de_stock

        # 2. Manejo de Stock (JIT)
        if tomar_de_stock > 0:
            stock_virtual_pt[producto_id] -= tomar_de_stock
            if ov.fecha_entrega.date() == tomorrow:
                print(f"   > Reservando JIT: {tomar_de_stock} de {linea_ov.id_producto.nombre} para OV {ov.id_orden_venta}")
                _reservar_stock_pt(linea_ov, tomar_de_stock, estado_reserva_activa)
            else:
                # No es para mañana, pero igual lo reservamos (esto es opcional)
                _reservar_stock_pt(linea_ov, tomar_de_stock, estado_reserva_activa)

        # 3. ¿Necesita Producción?
        if cantidad_para_producir > 0:
            print(f"   > OV {ov.id_orden_venta} (Línea {linea_ov.id_orden_venta_producto}) necesita PRODUCIR {cantidad_para_producir} de {linea_ov.id_producto.nombre}")
            lineas_para_producir.append((linea_ov, cantidad_para_producir))
            # Marcamos la OV como "En Preparación"
            if ov.id_estado_venta != estado_ov_en_preparacion:
                ov.id_estado_venta = estado_ov_en_preparacion
                ov.save(update_fields=['id_estado_venta'])
        
        elif tomar_de_stock >= linea_ov.cantidad:
             # Se cubrió 100% con stock, chequear si la OV está completa
             pass # (Lógica simplificada, asumimos que JIT la cierra)


    # ===================================================================
    # PASO 4, 5: SCHEDULING (MTO) Y CÁLCULO DE MP
    # (El corazón de la nueva lógica)
    # ===================================================================
    print(f"\n[PASO 4-5/6] Planificando OPs (MTO) para {len(lineas_para_producir)} líneas de OV...")

    # Limpiamos OPs 'En espera' que ya no tienen OVs vinculadas
    OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_op_en_espera,
        ovs_vinculadas__isnull=True
    ).delete()

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

            # --- B. CÁLCULO DE FECHA IDEAL DE INICIO ---
            fecha_planificada_ideal = fecha_entrega_ov - timedelta(days=dias_produccion_estimados) - timedelta(DIAS_BUFFER_ENTREGA_PT)
            if fecha_planificada_ideal < hoy:
                fecha_planificada_ideal = hoy

            # --- C. CREAR LA OP (¡NUEVA!) ---
            # Creamos una OP FRESCA para esta línea de OV
            op = OrdenProduccion.objects.create(
                id_producto=producto,
                id_estado_orden_produccion=estado_op_en_espera, # Default
                cantidad=cantidad_a_producir,
                fecha_planificada=fecha_planificada_ideal # Temporal
            )
            
            # --- ❗️ CREAR EL VÍNCULO (PEGGING) ---
            OrdenProduccionPegging.objects.create(
                id_orden_produccion=op,
                id_orden_venta_producto=linea_ov,
                cantidad_asignada=cantidad_a_producir
            )
            print(f"      > CREADA OP {op.id_orden_produccion} (MTO) y vinculada a OV {ov.id_orden_venta}.")

            # --- D. LÓGICA "WALK THE CALENDAR" ---
            horas_pendientes = horas_necesarias_totales
            fecha_a_buscar = fecha_planificada_ideal
            fecha_inicio_real_asignada = None
            fecha_fin_real_asignada = None
            reservas_a_crear_bulk = []
            
            print(f"      > Buscando hueco desde {fecha_a_buscar}...")

            while horas_pendientes > 0:
                horas_libres_cuello_botella = HORAS_LABORABLES_POR_DIA
                lineas_ids_producto = [c.id_linea_produccion_id for c in capacidades_linea]
                
                # Buscamos carga de OPs "En espera" o "Pendiente de inicio"
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

                for cap_linea in capacidades_linea:
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
                
                print(f"      > Reservadas {horas_a_reservar_hoy}hs enteras en {fecha_a_buscar}. Faltan {horas_pendientes}hs.")
                fecha_a_buscar += timedelta(days=1)
            
            fecha_fin_real_asignada = fecha_a_buscar - timedelta(days=1)

            # --- E. GUARDAR OP Y RESERVAS DE CALENDARIO ---
            op.fecha_planificada = fecha_inicio_real_asignada
            op.fecha_fin_planificada = fecha_fin_real_asignada
            op.save(update_fields=['fecha_planificada', 'fecha_fin_planificada'])
            CalendarioProduccion.objects.bulk_create(reservas_a_crear_bulk)
            print(f"      -> PLANIFICACIÓN REAL: {op.fecha_planificada} a {op.fecha_fin_planificada}.")


            # --- F. REPROGRAMACIÓN DE OV (MTO) ---
            
            nueva_fecha_entrega_sugerida_date = op.fecha_fin_planificada + timedelta(days=DIAS_BUFFER_ENTREGA_PT)

            if nueva_fecha_entrega_sugerida_date > ov.fecha_entrega.date():
                print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print(f"      !!! ALERTA DE ENTREGA: OP {op.id_orden_produccion}")
                print(f"      !!! Vinculada a: OV {ov.id_orden_venta} (Entrega actual: {ov.fecha_entrega.date()})")
                print(f"      !!! Producción termina el: {op.fecha_fin_planificada}")
                print(f"      !!! Nueva fecha de entrega sugerida: {nueva_fecha_entrega_sugerida_date}")
                print(f"      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                hora_original = ov.fecha_entrega.time()
                nueva_fecha_naive = datetime.combine(nueva_fecha_entrega_sugerida_date, hora_original)
                nueva_fecha_entrega_aware = timezone.make_aware(nueva_fecha_naive)

                print(f"      !!! DESPLAZANDO OV {ov.id_orden_venta} a {nueva_fecha_entrega_aware.date()}")
                
                ov.fecha_entrega = nueva_fecha_entrega_aware
                ov.id_estado_venta = estado_ov_en_preparacion 
                ov.save(update_fields=['fecha_entrega', 'id_estado_venta'])

            # --- G. LÓGICA DE LOTE ---
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


            # --- H. (PASO 5) CHEQUEO DE MP Y ESTADO ---
            print(f"      > [PASO 5/6] Calculando MP y Estado para OP {op.id_orden_produccion}...")
            
            receta = Receta.objects.get(id_producto=op.id_producto)
            ingredientes_totales = RecetaMateriaPrima.objects.filter(id_receta=receta)
            max_lead_time_mp = 0
            op_tiene_todo_el_material_EN_STOCK = True

            for ingr in ingredientes_totales:
                # ... (Lógica de chequeo de MP: _reservar_stock_mp, stock_virtual_oc, compras_agregadas) ...
                # (Es la misma lógica del PASO 5 anterior, no cambia)
                mp_id = ingr.id_materia_prima_id
                mp = ingr.id_materia_prima
                proveedor = mp.id_proveedor
                cantidad_requerida_op = ingr.cantidad * op.cantidad
                cantidad_faltante_op = cantidad_requerida_op

                stock_mp_disponible = stock_virtual_mp.get(mp_id, 0)
                tomar_de_stock = min(stock_mp_disponible, cantidad_faltante_op)
                
                if tomar_de_stock > 0:
                    _reservar_stock_mp(op, mp_id, tomar_de_stock, estado_reserva_mp_activa)
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
                    print(f"      ! Faltan {cantidad_a_comprar} de {mp.nombre} para OP {op.id_orden_produccion}. Agregando a OC.")
                    lead_proveedor = ingr.id_materia_prima.id_proveedor.lead_time_days
                    max_lead_time_mp = max(max_lead_time_mp, lead_proveedor)
                    compra_agregada = compras_agregadas_por_proveedor[proveedor.id_proveedor]
                    compra_agregada["proveedor"] = proveedor
                    compra_agregada["items"][mp_id] += cantidad_a_comprar
                    fecha_requerida_mp = op.fecha_planificada - timedelta(days=DIAS_BUFFER_RECEPCION_MP)
                    if fecha_requerida_mp < compra_agregada["fecha_requerida_mas_temprana"]:
                        compra_agregada["fecha_requerida_mas_temprana"] = fecha_requerida_mp

            # --- I. ACTUALIZAR ESTADO Y FECHA INICIO DE OP ---
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
            if op and op.pk: op.delete() # Borra la OP fallida
        except Exception as e:
            print(f"      !ERROR al planificar OP para {producto.nombre}: {e}")
            if op and op.pk: op.delete() # Borra la OP fallida
            
    # ===================================================================
    # PASO 6: CREAR ÓRDENES DE COMPRA (AGRUPADAS)
    # (Esta lógica se movió al final, fuera del bucle MTO)
    # ===================================================================
    print(f"\n[PASO 6/6] Creando {len(compras_agregadas_por_proveedor)} OCs agrupadas por proveedor...")

    for proveedor_id, info in compras_agregadas_por_proveedor.items():
        # ... (La lógica de creación de OCs es idéntica a la versión anterior) ...
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