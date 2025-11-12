from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta, Factura, NotaCredito
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from django.db.models import Sum, F, Q

@transaction.atomic
def registrar_orden_venta_y_actualizar_estado(orden_venta: OrdenVenta):
    """
    Simplemente guarda la orden de venta y la pone en estado 'Creada'.
    No reserva stock ni crea Órdenes de Producción.
    Deja la orden lista para que el planificador (MRP) la procese.
    """
    # Obtenemos el estado "Creada"
    estado_creada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Creada")
    
    # Asignamos el estado a la orden
    orden_venta.id_estado_venta = estado_creada
    orden_venta.save()
    
    print(f"Orden Venta #{orden_venta.pk} guardada. Estado -> Creada. Esperando al planificador.")


@transaction.atomic
def facturar_orden_y_descontar_stock(orden_venta: OrdenVenta):
    """
    (Esta función se mantiene como estaba)
    Descuenta el stock físico que el PLANIFICADOR ya reservó.
    """
    print(f"Iniciando facturación y descuento físico para la Orden #{orden_venta.pk}...")
    
    reservas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva__descripcion="Activa"
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')
    
    # ... (El resto de la función sigue igual) ...
    estado_agotado, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Agotado")
    productos_afectados = set()

    for reserva in reservas:
        lote = reserva.id_lote_produccion
        cantidad_a_descontar = reserva.cantidad_reservada
        lote.cantidad -= cantidad_a_descontar
        if lote.cantidad <= 0:
            lote.cantidad = 0 # Asegurar que no sea negativo
            lote.id_estado_lote_produccion = estado_agotado
        lote.save()
        productos_afectados.add(reserva.id_orden_venta_producto.id_producto.pk)

    estado_utilizada, _ = EstadoReserva.objects.get_or_create(descripcion="Utilizada")
    reservas.update(id_estado_reserva=estado_utilizada)
    
    estado_facturada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pagada")
    orden_venta.id_estado_venta = estado_facturada
    orden_venta.save()

    print("Verificando umbrales de stock post-facturación...")
    for producto_id in productos_afectados:
        verificar_stock_y_enviar_alerta(producto_id)

    print(f"Orden #{orden_venta.pk} facturada y stock físico descontado exitosamente.")


@transaction.atomic
def cancelar_orden_venta(orden_venta):
    """
    (Esta función se mantiene como estaba)
    Cancela una orden y libera las reservas que el PLANIFICADOR hizo.
    """
    print(f"Cancelando Orden Venta #{orden_venta.pk}...")
    estado_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_cancelada, _ = EstadoReserva.objects.get_or_create(descripcion="Cancelada")

    reservas_a_cancelar = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    )
    

    reservas_a_cancelar.update(id_estado_reserva=estado_cancelada)
    
    estado_orden_cancelada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_orden_cancelada
    orden_venta.save()
    
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")
    
 


@transaction.atomic
def crear_nota_credito_y_devolver_stock(orden_venta: OrdenVenta, motivo: str = None):
    """
    1. Crea una Nota de Crédito para la factura de la orden.
    2. Encuentra las reservas 'Utilizadas' de esa orden.
    3. Devuelve el stock físico (cantidad) a los lotes correspondientes.
    4. Cambia el estado de los lotes a 'Disponible' si estaban 'Agotados'.
    5. Cambia el estado de las reservas a 'Devolución NC'.
    6. Cambia el estado de la orden a 'Devolución NC'.
    7. Dispara la re-evaluación de stock para otras órdenes pendientes.
    """
    print(f"Iniciando creación de Nota de Crédito para Orden #{orden_venta.pk}...")

    # 1. Validar estado de la orden y encontrar factura
    estado_facturada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pagada")
    if orden_venta.id_estado_venta != estado_facturada:
        raise Exception(f"La orden #{orden_venta.pk} no está 'Pagada'. No se puede crear nota de crédito.")

    try:
        factura = Factura.objects.get(id_orden_venta=orden_venta)
    except Factura.DoesNotExist:
        raise Exception(f"No se encontró una factura para la orden #{orden_venta.pk}.")

    # 2. Validar que no exista ya una NC
    if NotaCredito.objects.filter(id_factura=factura).exists():
        raise Exception(f"Ya existe una nota de crédito para la factura #{factura.pk}.")

    # 3. Obtener estados necesarios
    estado_utilizada = EstadoReserva.objects.get(descripcion="Utilizada")
    estado_devuelta_nc, _ = EstadoReserva.objects.get_or_create(descripcion="Devolución NC")
    estado_disponible, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Disponible")
    estado_orden_devuelta, _ = EstadoVenta.objects.get_or_create(descripcion="Devolución NC")

    # 4. Encontrar las reservas que se usaron para esta orden
    reservas_utilizadas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_utilizada
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')

    if not reservas_utilizadas.exists():
        raise Exception(f"No se encontraron reservas 'Utilizadas' para la orden #{orden_venta.pk}. No se puede revertir el stock.")

    # 5. Crear la Nota de Crédito
    nota_credito = NotaCredito.objects.create(
        id_factura=factura,
        motivo=motivo or "Devolución de cliente"
    )

    productos_afectados = set()

    # 6. Devolver el stock a los lotes
    for reserva in reservas_utilizadas:
        lote = reserva.id_lote_produccion
        cantidad_a_devolver = reserva.cantidad_reservada

        print(f"  > Devolviendo {cantidad_a_devolver} unidades al Lote #{lote.pk} (Producto: {reserva.id_orden_venta_producto.id_producto.nombre})")

        # Devolvemos la cantidad
        lote.cantidad = F('cantidad') + cantidad_a_devolver
        
        # Si el lote estaba 'Agotado', vuelve a estar 'Disponible'
        lote.id_estado_lote_produccion = estado_disponible
        
        lote.save()
        productos_afectados.add(reserva.id_orden_venta_producto.id_producto)

    # 7. Actualizar estado de las reservas
    reservas_utilizadas.update(id_estado_reserva=estado_devuelta_nc)

    # 8. Actualizar estado de la Orden de Venta
    orden_venta.id_estado_venta = estado_orden_devuelta
    orden_venta.save()


    return nota_credito