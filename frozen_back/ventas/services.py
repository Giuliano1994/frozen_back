from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta, Factura, NotaCredito
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import get_stock_disponible_para_producto, verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from productos.models import Producto
from produccion.models import OrdenProduccion, EstadoOrdenProduccion
from recetas.models import ProductoLinea, Receta
from empleados.models import Empleado
from django.utils import timezone
from datetime import timedelta
from produccion.services import gestionar_reservas_para_orden_produccion
from compras.models import OrdenCompra, OrdenCompraProduccion, EstadoOrdenCompra
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Q



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
    lineas_de_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    estado_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")

    if not lineas_de_orden.exists():
        estado_final, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Creada")
        orden_venta.id_estado_venta = estado_final
        orden_venta.save()
        return

    # --- LÓGICA INCREMENTAL ---
    # 1. Intentamos reservar lo que falte para cada producto
    for linea in lineas_de_orden:
        # Calculamos cuánto ya está reservado para esta línea
        cantidad_ya_reservada = linea.reservas.filter(id_estado_reserva=estado_activa).aggregate(
            total=Sum('cantidad_reservada')
        )['total'] or 0
        
        cantidad_faltante_a_reservar = linea.cantidad - cantidad_ya_reservada

        if cantidad_faltante_a_reservar > 0:
            print(f"Producto '{linea.id_producto.nombre}': Faltan {cantidad_faltante_a_reservar} unidades por reservar. Buscando stock...")
            lotes_disponibles = LoteProduccion.objects.filter(
                id_producto=linea.id_producto,
                id_estado_lote_produccion__descripcion="Disponible"
            ).order_by('fecha_vencimiento')

            for lote in lotes_disponibles:
                if cantidad_faltante_a_reservar <= 0: break
                
                stock_real_disponible_lote = lote.cantidad_disponible
                cantidad_a_tomar_de_lote = min(cantidad_faltante_a_reservar, stock_real_disponible_lote)

                if cantidad_a_tomar_de_lote > 0:
                    ReservaStock.objects.create(
                        id_orden_venta_producto=linea,
                        id_lote_produccion=lote,
                        cantidad_reservada=cantidad_a_tomar_de_lote,
                        id_estado_reserva=estado_activa
                    )
                    cantidad_faltante_a_reservar -= cantidad_a_tomar_de_lote
                    print(f"  > Reservadas {cantidad_a_tomar_de_lote} unidades del lote #{lote.pk}.")

            # Si después de intentar reservar sigue faltando, creamos una orden de producción
            # para ESTE producto (independientemente de cuántas líneas tenga la orden de venta).
            if cantidad_faltante_a_reservar > 0:
                try:
                    # Obtener la velocidad de producción (cant_por_hora) asociada al producto
                    producto_linea = ProductoLinea.objects.filter(id_producto=linea.id_producto).first()
                    cant_por_hora = producto_linea.cant_por_hora if producto_linea and producto_linea.cant_por_hora else None
                    if not cant_por_hora or cant_por_hora <= 0:
                        print(f"No se encontró 'cant_por_hora' para el producto {linea.id_producto.nombre}. No se creará orden de producción.")
                    else:
                        # Calcular múltiplo de cant_por_hora necesario para cubrir lo faltante
                        faltante = cantidad_faltante_a_reservar
                        multiplo = (faltante + cant_por_hora - 1) // cant_por_hora
                        cantidad_a_producir = multiplo * cant_por_hora

                        # Obtener o crear estado "En espera" de forma segura
                        estado_en_espera = EstadoOrdenProduccion.objects.filter(descripcion__iexact="En espera").first()
                        if not estado_en_espera:
                            estado_en_espera = EstadoOrdenProduccion.objects.create(descripcion="En espera")

                        # Asignar un supervisor por defecto si existe alguno (evita que el front falle por ausencia de campo)
                        default_supervisor = Empleado.objects.first()

                        orden_prod = OrdenProduccion.objects.create(
                            cantidad=cantidad_a_producir,
                            id_estado_orden_produccion=estado_en_espera,
                            id_producto=linea.id_producto,
                            id_orden_venta=orden_venta,
                            #id_linea_produccion=(producto_linea.id_linea_produccion if producto_linea and getattr(producto_linea, 'id_linea_produccion', None) else None),
                            id_supervisor=default_supervisor,
                        )
                        print(f"Creada OrdenProduccion #{orden_prod.id_orden_produccion} para producir {cantidad_a_producir} unidades (múltiplo de {cant_por_hora}) asociada a OrdenVenta #{orden_venta.pk}")

                        # Programar la gestión de reservas para que se ejecute después del commit
                        try:
                            transaction.on_commit(lambda op=orden_prod: gestionar_reservas_para_orden_produccion(op))
                        except Exception as e:
                            # on_commit rarely falla; si ocurre, lo registramos
                            print(f"Error al programar la gestión de reservas para la orden de producción {orden_prod.pk}: {e}")
                        # Crear lote de producción asociado a la orden (mismo comportamiento que en el ViewSet)
                        try:
                            estado_lote_espera = EstadoLoteProduccion.objects.filter(descripcion__iexact="En espera").first()
                            if not estado_lote_espera:
                                estado_lote_espera = EstadoLoteProduccion.objects.create(descripcion="En espera")

                            dias = getattr(orden_prod.id_producto, 'dias_duracion', 0) or 0
                            lote = LoteProduccion.objects.create(
                                id_producto=orden_prod.id_producto,
                                id_estado_lote_produccion=estado_lote_espera,
                                cantidad=orden_prod.cantidad,
                                fecha_produccion=timezone.now().date(),
                                fecha_vencimiento=timezone.now().date() + timedelta(days=dias)
                            )

                            orden_prod.id_lote_produccion = lote
                            orden_prod.save()
                        except Exception as e:
                            print(f"Error creando lote de producción para OrdenProduccion {getattr(orden_prod,'id_orden_produccion', 'n/a')}: {e}")
                except Exception as e:
                    print(f"Error creando orden de producción para la orden de venta {orden_venta.pk}: {e}")

    # --- RE-EVALUACIÓN FINAL ---
    # 2. Después de intentar reservar, verificamos si la orden está completa
    stock_completo_final = True
    for linea in lineas_de_orden:
        cantidad_total_reservada = linea.reservas.filter(id_estado_reserva=estado_activa).aggregate(
            total=Sum('cantidad_reservada')
        )['total'] or 0
        
        if cantidad_total_reservada < linea.cantidad:
            stock_completo_final = False
            break

    # 3. Asignar el estado final
    if stock_completo_final:
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

    # --- CAMBIO CLAVE 1: Obtenemos los productos afectados ANTES de cancelar ---
    # Necesitamos saber qué productos se liberaron para poder re-evaluar otras órdenes.
    reservas_a_cancelar = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    )
    productos_liberados = set(
        reserva.id_orden_venta_producto.id_producto for reserva in reservas_a_cancelar.select_related('id_orden_venta_producto__id_producto')
    )

    # Cancelamos las reservas activas
    reservas_a_cancelar.update(id_estado_reserva=estado_cancelada)
   
    """
    # --- CAMBIO CLAVE: En lugar de borrar, cancelamos las reservas activas ---
    ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    ).update(id_estado_reserva=estado_cancelada)
    """

    # Actualizar el estado de la orden
    estado_orden_cancelada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_orden_cancelada
    orden_venta.save()
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")

    # --- CAMBIO CLAVE 2: Disparamos la re-evaluación para cada producto liberado ---
    for producto in productos_liberados:
        revisar_ordenes_de_venta_pendientes(producto)





   

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
    ).distinct().order_by('fecha_entrega')

    if not ordenes_a_revisar.exists():
        print("No se encontraron órdenes de venta pendientes para este producto.")
        return

    print(f"Se encontraron {ordenes_a_revisar.count()} órdenes de venta para re-evaluar.")

    # Para cada orden encontrada, simplemente volvemos a ejecutar el servicio principal.
    # Este servicio se encargará de verificar si AHORA el stock es completo y cambiará el estado si es necesario.
    for orden in ordenes_a_revisar:
        print(f"Re-evaluando Orden de Venta #{orden.pk}...")
        gestionar_stock_y_estado_para_orden_venta(orden)





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

    print(f"Nota de Crédito #{nota_credito.pk} creada exitosamente.")
    print("Disparando re-evaluación de órdenes pendientes por stock devuelto...")

    # 9. (CRUCIAL) Disparar la re-evaluación de stock para órdenes pendientes
    #    Usamos la misma función que usa 'cancelar_orden_venta'
    for producto in productos_afectados:
        revisar_ordenes_de_venta_pendientes(producto)

    return nota_credito