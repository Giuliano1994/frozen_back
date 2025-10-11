from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta 
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import get_stock_disponible_para_producto, verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from productos.models import Producto

"""

def _descontar_stock_fisico(orden_venta):
    
    #Función auxiliar para descontar el stock físico de los lotes.
    #Se usa cuando sabemos que hay stock suficiente para toda la orden.
    
    lineas_de_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    estado_disponible = EstadoLoteProduccion.objects.get(descripcion="Disponible")
    estado_agotado, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Agotado")

    for linea in lineas_de_orden:
        cantidad_a_descontar = linea.cantidad
        lotes = LoteProduccion.objects.filter(
            id_producto=linea.id_producto,
            id_estado_lote_produccion=estado_disponible,
            cantidad__gt=0
        ).order_by("fecha_vencimiento")

        for lote in lotes:
            if cantidad_a_descontar <= 0: break
            
            cantidad_tomada = min(lote.cantidad, cantidad_a_descontar)
            
            lote.cantidad -= cantidad_tomada
            cantidad_a_descontar -= cantidad_tomada
            
            if lote.cantidad == 0:
                lote.id_estado_lote_produccion = estado_agotado
            
            lote.save()

def _reservar_stock_parcial(orden_venta):
    
    #Función auxiliar para reservar el stock que haya disponible.
    #Se usa cuando el stock no es suficiente para cubrir toda la orden.
    
    # Limpiamos reservas previas para esta orden por si se re-ejecuta.
    ReservaStock.objects.filter(id_orden_venta_producto__id_orden_venta=orden_venta).delete()

    lineas_de_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    for linea in lineas_de_orden:
        cantidad_a_reservar = linea.cantidad
        
        lotes_disponibles = LoteProduccion.objects.filter(
            id_producto=linea.id_producto,
            cantidad__gt=0,
            id_estado_lote_produccion__descripcion="Disponible"
        ).order_by('fecha_vencimiento')

        for lote in lotes_disponibles:
            if cantidad_a_reservar <= 0: break

            stock_real_disponible_lote = lote.cantidad_disponible
            cantidad_reservada_de_lote = min(cantidad_a_reservar, stock_real_disponible_lote)

            if cantidad_reservada_de_lote > 0:
                ReservaStock.objects.create(
                    id_orden_venta_producto=linea,
                    id_lote_produccion=lote,
                    cantidad_reservada=cantidad_reservada_de_lote
                )
                cantidad_a_reservar -= cantidad_reservada_de_lote

# --- FUNCIÓN PRINCIPAL Y ORQUESTADORA ---
@transaction.atomic
def gestionar_stock_y_estado_para_orden_venta(orden_venta):
    
    #Orquesta todo el proceso de gestión de stock para una orden de venta.
    #Decide si descontar stock directamente o crear una reserva parcial.
    
    lineas_de_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    
    if not lineas_de_orden.exists():
        # Si no hay productos, no hay nada que hacer con el stock.
        return

    # 1. Verificar si hay stock completo para TODA la orden
    stock_completo = True
    for linea in lineas_de_orden:
        stock_disponible = get_stock_disponible_para_producto(linea.id_producto.pk)
        if stock_disponible < linea.cantidad:
            stock_completo = False
            break

    # 2. Actuar según el resultado
    if stock_completo:
        print(f"Stock completo para la Orden #{orden_venta.pk}. Descontando stock físico...")
        # CASO 1: Hay stock, se descuenta directamente
        _descontar_stock_fisico(orden_venta)
        estado_final = EstadoVenta.objects.get(descripcion__iexact="Pendiente de Pago")
    else:
        print(f"Stock incompleto para la Orden #{orden_venta.pk}. Reservando stock disponible...")
        # CASO 2: No hay stock, se reserva lo que se pueda
        _reservar_stock_parcial(orden_venta)
        estado_final = EstadoVenta.objects.get(descripcion__iexact="En Preparación")
    
    # 3. Actualizar el estado final de la orden
    orden_venta.id_estado_venta = estado_final
    orden_venta.save()

    for linea in lineas_de_orden:
        verificar_stock_y_enviar_alerta(linea.id_producto.pk)

    
        

        
def cancelar_orden_venta(orden_venta):
    
    #Libera todo el stock reservado y cambia el estado de la orden a 'Cancelada'.
    
    # Liberar todo el stock reservado para esta orden
    ReservaStock.objects.filter(id_orden_venta_producto__id_orden_venta=orden_venta).delete()
    
    # Actualizar el estado
    estado_cancelada = EstadoVenta.objects.get(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_cancelada
    orden_venta.save()
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")



"""

# --- NUEVA FUNCIÓN PARA EL PASO FINAL DE FACTURACIÓN ---
# --- MÉTODO EDITADO ---
@transaction.atomic
def facturar_orden_y_descontar_stock(orden_venta: OrdenVenta):
    """
    1. Descuenta el stock físico basándose en las reservas ACTIVAS.
    2. Cambia el estado de las reservas a 'Utilizada'.
    3. Cambia el estado de la orden a 'Facturada'.
    4. Verifica umbrales de stock post-descuento.
    """
    print(f"Iniciando facturación y descuento físico para la Orden #{orden_venta.pk}...")
    
    # --- CAMBIO CLAVE: Filtramos solo las reservas en estado 'Activa' ---
    reservas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva__descripcion="Activa"
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')
    
    if not reservas.exists():
        print(f"Advertencia: La orden #{orden_venta.pk} no tiene stock activo reservado para facturar.")
        # Opcional: Podrías lanzar un error aquí.

    estado_agotado, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Agotado")
    productos_afectados = set()

    for reserva in reservas:
        lote = reserva.id_lote_produccion
        cantidad_a_descontar = reserva.cantidad_reservada

        lote.cantidad -= cantidad_a_descontar
        
        if lote.cantidad < 0:
            raise Exception(f"Error de consistencia: El stock del lote #{lote.pk} es negativo.")

        if lote.cantidad == 0:
            lote.id_estado_lote_produccion = estado_agotado
        
        lote.save()
        productos_afectados.add(reserva.id_orden_venta_producto.id_producto.pk)

    # --- CAMBIO CLAVE: En lugar de borrar, actualizamos el estado a 'Utilizada' ---
    estado_utilizada, _ = EstadoReserva.objects.get_or_create(descripcion="Utilizada")
    reservas.update(id_estado_reserva=estado_utilizada)
    
    # Cambiar el estado de la orden
    estado_facturada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pagada")
    orden_venta.id_estado_venta = estado_facturada
    orden_venta.save()

    # La alerta de umbral se llama aquí
    print("Verificando umbrales de stock post-facturación...")
    for producto_id in productos_afectados:
        verificar_stock_y_enviar_alerta(producto_id)

    print(f"Orden #{orden_venta.pk} facturada y stock físico descontado exitosamente.")

# --- MÉTODO EDITADO ---
@transaction.atomic
def gestionar_stock_y_estado_para_orden_venta(orden_venta: OrdenVenta):
    """
    Orquesta el proceso de RESERVA de stock.
    1. Cancela las reservas activas anteriores de la orden.
    2. Crea nuevas reservas 'Activas'.
    3. Asigna el estado a la orden según si la reserva fue completa o parcial.
    """
    # Obtenemos los estados que vamos a usar
    estado_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_cancelada, _ = EstadoReserva.objects.get_or_create(descripcion="Cancelada")

    # --- CAMBIO CLAVE: En lugar de borrar, cancelamos las reservas activas anteriores ---
    ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    ).update(id_estado_reserva=estado_cancelada)

    lineas_de_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    
    if not lineas_de_orden.exists():
        estado_final, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Creada")
        orden_venta.id_estado_venta = estado_final
        orden_venta.save()
        return

    stock_completo = True
    for linea in lineas_de_orden:
        stock_disponible = get_stock_disponible_para_producto(linea.id_producto.pk)
        if stock_disponible < linea.cantidad:
            stock_completo = False
            break

    print(f"Gestionando reservas para la Orden #{orden_venta.pk}...")
    for linea in lineas_de_orden:
        cantidad_a_reservar = linea.cantidad
        lotes_disponibles = LoteProduccion.objects.filter(
            id_producto=linea.id_producto,
            id_estado_lote_produccion__descripcion="Disponible"
        ).order_by('fecha_vencimiento')

        for lote in lotes_disponibles:
            if cantidad_a_reservar <= 0: break
            stock_real_disponible_lote = lote.cantidad_disponible
            cantidad_reservada_de_lote = min(cantidad_a_reservar, stock_real_disponible_lote)

            if cantidad_reservada_de_lote > 0:
                # --- CAMBIO CLAVE: Asignamos el estado 'Activa' al crear la reserva ---
                ReservaStock.objects.create(
                    id_orden_venta_producto=linea,
                    id_lote_produccion=lote,
                    cantidad_reservada=cantidad_reservada_de_lote,
                    id_estado_reserva=estado_activa  # <-- Se asigna el estado
                )
                cantidad_a_reservar -= cantidad_reservada_de_lote

    # Asignar el estado basado en si la reserva fue completa
    if stock_completo:
        estado_final, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pendiente de Pago")
    else:
        estado_final, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="En Preparación")
    
    orden_venta.id_estado_venta = estado_final
    orden_venta.save()

def cancelar_orden_venta(orden_venta):
    """
    Cambia el estado de las reservas activas a 'Cancelada' y actualiza el estado de la orden.
    """
    # Obtenemos los estados que vamos a usar
    estado_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_cancelada, _ = EstadoReserva.objects.get_or_create(descripcion="Cancelada")

    # --- CAMBIO CLAVE: En lugar de borrar, cancelamos las reservas activas ---
    ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    ).update(id_estado_reserva=estado_cancelada)
    
    # Actualizar el estado de la orden
    estado_orden_cancelada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_orden_cancelada
    orden_venta.save()
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")







   

def revisar_ordenes_de_venta_pendientes(producto: Producto):
    """
    Busca órdenes de venta en estado 'En Preparación' que contengan el producto
    que acaba de ingresar a stock, y re-evalúa su estado y reservas.
    """
    print(f"--- Disparador de stock: Revisando órdenes de venta en 'En Preparación' para el producto: {producto.nombre} ---")
    
    try:
        # Buscamos el estado que nos interesa
        estado_en_preparacion = EstadoVenta.objects.get(descripcion__iexact="En Preparación")
    except EstadoVenta.DoesNotExist:
        print("Advertencia: No se encontró el estado 'En Preparación'. No se puede continuar.")
        return

    # Buscamos todas las órdenes de venta que:
    # 1. Estén en estado "En Preparación".
    # 2. Contengan el producto específico en alguna de sus líneas.
    # Usamos .distinct() para no procesar la misma orden varias veces si tuviera el mismo producto en múltiples líneas.
    ordenes_a_revisar = OrdenVenta.objects.filter(
        id_estado_venta=estado_en_preparacion,
        ordenventaproducto__id_producto=producto
    ).distinct()

    if not ordenes_a_revisar.exists():
        print("No se encontraron órdenes de venta pendientes para este producto.")
        return

    print(f"Se encontraron {ordenes_a_revisar.count()} órdenes de venta para re-evaluar.")

    # Para cada orden encontrada, simplemente volvemos a ejecutar el servicio principal.
    # Este servicio se encargará de verificar si AHORA el stock es completo y cambiará el estado si es necesario.
    for orden in ordenes_a_revisar:
        print(f"Re-evaluando Orden de Venta #{orden.pk}...")
        gestionar_stock_y_estado_para_orden_venta(orden)