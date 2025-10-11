from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion
from stock.services import get_stock_disponible_para_producto, verificar_stock_y_enviar_alerta
from stock.models import ReservaStock



def _descontar_stock_fisico(orden_venta):
    """
    Función auxiliar para descontar el stock físico de los lotes.
    Se usa cuando sabemos que hay stock suficiente para toda la orden.
    """
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
    """
    Función auxiliar para reservar el stock que haya disponible.
    Se usa cuando el stock no es suficiente para cubrir toda la orden.
    """
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
    """
    Orquesta todo el proceso de gestión de stock para una orden de venta.
    Decide si descontar stock directamente o crear una reserva parcial.
    """
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
    """
    Libera todo el stock reservado y cambia el estado de la orden a 'Cancelada'.
    """
    # Liberar todo el stock reservado para esta orden
    ReservaStock.objects.filter(id_orden_venta_producto__id_orden_venta=orden_venta).delete()
    
    # Actualizar el estado
    estado_cancelada = EstadoVenta.objects.get(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_cancelada
    orden_venta.save()
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")