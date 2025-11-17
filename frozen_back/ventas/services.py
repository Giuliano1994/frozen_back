from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta, Factura, NotaCredito
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from django.db.models import Sum, F, Q

from datetime import date, timedelta
from django.utils import timezone
import math

# Importar modelos
from productos.models import Producto
from recetas.models import Receta, RecetaMateriaPrima, ProductoLinea
from produccion.models import CalendarioProduccion, EstadoOrdenProduccion
from stock.services import get_stock_disponible_para_producto, get_stock_disponible_para_materia_prima

# Constantes (Las mismas de tu planificador)
HORAS_LABORABLES_POR_DIA = 16
DIAS_BUFFER_ENTREGA_PT = 1
DIAS_BUFFER_RECEPCION_MP = 1



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






def calcular_fecha_estimada_entrega(id_producto, cantidad_solicitada):
    """
    Calcula la fecha de entrega más temprana posible (CTP) 
    basada en Stock PT, Lead Time de MP y Capacidad de Máquina.
    """
    hoy = timezone.now().date()
    
    # 1. Verificar Stock de Producto Terminado (PT)
    stock_pt_actual = get_stock_disponible_para_producto(id_producto)
    
    # Si hay suficiente stock ya fabricado
    if stock_pt_actual >= cantidad_solicitada:
        # Entrega inmediata (mañana)
        fecha_entrega = hoy + timedelta(days=1)
        while fecha_entrega.weekday() >= 5: fecha_entrega += timedelta(days=1)
        return {
            "es_posible": True,
            "fecha_estimada": fecha_entrega,
            "origen": "Stock Existente"
        }

    # Si falta, calculamos cuánto hay que producir
    cantidad_a_producir = cantidad_solicitada - stock_pt_actual
    
    # 2. Calcular Disponibilidad de Materia Prima (MP) y Lead Time
    max_lead_time_mp = 0
    try:
        receta = Receta.objects.get(id_producto=id_producto)
        ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
        
        for ing in ingredientes:
            cantidad_necesaria = ing.cantidad * cantidad_a_producir
            stock_mp = get_stock_disponible_para_materia_prima(ing.id_materia_prima.id_materia_prima)
            
            if stock_mp < cantidad_necesaria:
                # Falta material, buscamos el Lead Time del proveedor
                lead_prov = ing.id_materia_prima.id_proveedor.lead_time_days
                if lead_prov > max_lead_time_mp:
                    max_lead_time_mp = lead_prov
                    
    except Receta.DoesNotExist:
        return {"error": "El producto no tiene receta activa."}

    # Calcular fecha llegada materiales
    fecha_llegada_mp = hoy + timedelta(days=max_lead_time_mp)
    while fecha_llegada_mp.weekday() >= 5: fecha_llegada_mp += timedelta(days=1)
    
    # Fecha inicio producción (después del buffer MP)
    fecha_inicio_prod = fecha_llegada_mp + timedelta(days=DIAS_BUFFER_RECEPCION_MP)
    while fecha_inicio_prod.weekday() >= 5: fecha_inicio_prod += timedelta(days=1)

    # 3. Calcular Tiempo de Producción (Capacidad)
    capacidades = ProductoLinea.objects.filter(id_producto=id_producto)
    if not capacidades.exists():
         return {"error": "El producto no tiene líneas de producción asignadas."}
         
    capacidad_total_hora = capacidades.aggregate(total=Sum('cant_por_hora'))['total'] or 0
    if capacidad_total_hora <= 0:
         return {"error": "Capacidad de producción es 0."}
         
    horas_necesarias = math.ceil(cantidad_a_producir / capacidad_total_hora)
    
    # 4. "Walk the Calendar" (Solo lectura) para ver huecos disponibles
    # Buscamos cuándo terminaría realmente considerando la carga actual de la fábrica
    fecha_cursor = fecha_inicio_prod
    horas_pendientes = horas_necesarias
    
    lineas_ids = [c.id_linea_produccion_id for c in capacidades]
    
    # Estados que ocupan máquina
    estados_ocupados = ["En espera", "Pendiente de inicio", "En proceso"] 
    
    while horas_pendientes > 0:
        # Saltar fines de semana
        while fecha_cursor.weekday() >= 5: fecha_cursor += timedelta(days=1)
        
        # Consultar cuánto está ocupado ese día
        carga_existente = CalendarioProduccion.objects.filter(
            id_linea_produccion_id__in=lineas_ids,
            fecha=fecha_cursor,
            id_orden_produccion__id_estado_orden_produccion__descripcion__in=estados_ocupados
        ).aggregate(total=Sum('horas_reservadas'))['total'] or 0
        
        # Se asume que las líneas trabajan en paralelo, tomamos el promedio de ocupación o 
        # simplificamos asumiendo que el cuello de botella dicta el día.
        # Para el chequeo rápido, asumimos capacidad total del día:
        horas_disponibles_hoy = max(0, HORAS_LABORABLES_POR_DIA - float(carga_existente))
        
        # Si hay hueco, consumimos horas
        if horas_disponibles_hoy > 0:
            horas_a_tomar = min(horas_pendientes, horas_disponibles_hoy)
            horas_pendientes -= horas_a_tomar
        
        if horas_pendientes > 0:
            fecha_cursor += timedelta(days=1)

    fecha_fin_produccion = fecha_cursor
    
    # 5. Calcular Fecha Entrega Final
    fecha_entrega_calculada = fecha_fin_produccion + timedelta(days=DIAS_BUFFER_ENTREGA_PT + 1) # +1 seguridad
    while fecha_entrega_calculada.weekday() >= 5: fecha_entrega_calculada += timedelta(days=1)

    return {
        "es_posible": True,
        "fecha_estimada": fecha_entrega_calculada,
        "origen": "Producción (CTP)",
        "detalles": {
            "stock_actual": stock_pt_actual,
            "a_producir": cantidad_a_producir,
            "dias_espera_materiales": max_lead_time_mp,
            "fecha_inicio_prod": fecha_inicio_prod,
            "horas_produccion": horas_necesarias
        }
    }