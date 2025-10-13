
from django.db import transaction
from django.db.models import Sum
from .models import OrdenProduccion, EstadoOrdenProduccion
from stock.models import LoteMateriaPrima, EstadoLoteMateriaPrima, LoteProduccionMateria, ReservaMateriaPrima, EstadoReservaMateria
from recetas.models import Receta, RecetaMateriaPrima
from django.core.exceptions import ValidationError
from recetas.models import Receta, RecetaMateriaPrima


@transaction.atomic
def procesar_ordenes_en_espera(materia_prima_ingresada):
    """
    Busca órdenes de producción 'En espera' que necesiten la materia prima que acaba de ingresar.
    Si ahora tienen stock suficiente para TODOS sus ingredientes, las pasa a 'Pendiente de inicio'
    y descuenta el stock correspondiente.
    """
    print(f"Iniciando revisión de órdenes en espera por ingreso de: {materia_prima_ingresada.nombre}")

    # 1. Obtener los estados que vamos a necesitar
    try:
        estado_en_espera = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")
        estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")
        estado_disponible_mp = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")
    except (EstadoOrdenProduccion.DoesNotExist, EstadoLoteMateriaPrima.DoesNotExist) as e:
        print(f"Error: No se encontraron los estados necesarios en la BBDD. {e}")
        return

    # 2. Encontrar órdenes 'En espera' que usen esta materia prima en su receta
    ordenes_a_revisar = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_en_espera,
        id_producto__receta__recetamateriaprima__id_materia_prima=materia_prima_ingresada
    ).distinct()

    if not ordenes_a_revisar.exists():
        print("No hay órdenes en espera que requieran esta materia prima.")
        return

    print(f"Se encontraron {ordenes_a_revisar.count()} órdenes para revisar.")

    # 3. Iterar sobre cada orden y verificar si AHORA tiene stock completo
    for orden in ordenes_a_revisar:
        print(f"Revisando stock para la Orden de Producción #{orden.id_orden_produccion}...")
        
        try:
            receta = Receta.objects.get(id_producto=orden.id_producto)
            ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
            
            stock_suficiente = True
            # Volvemos a chequear el stock para TODOS los ingredientes de la orden
            for ingrediente in ingredientes:
                materia = ingrediente.id_materia_prima
                cantidad_necesaria = ingrediente.cantidad * orden.cantidad
                
                stock_total = LoteMateriaPrima.objects.filter(
                    id_materia_prima=materia,
                    id_estado_lote_materia_prima=estado_disponible_mp
                ).aggregate(total=Sum("cantidad"))["total"] or 0

                if stock_total < cantidad_necesaria:
                    stock_suficiente = False
                    print(f"Falta stock para {materia.nombre}. Se necesitan {cantidad_necesaria}, hay {stock_total}.")
                    break # Si falta un ingrediente, no hace falta seguir revisando

            # 4. Si hay stock para todo, cambiamos el estado y descontamos
            if stock_suficiente:
                print(f"¡Stock suficiente para la Orden #{orden.id_orden_produccion}! Procesando...")
                
                # Cambiar estado de la orden
                orden.id_estado_orden_produccion = estado_pendiente
                orden.save()
                
                # Descontar stock (lógica FIFO)
                for ingrediente in ingredientes:
                    materia = ingrediente.id_materia_prima
                    cantidad_a_descontar = ingrediente.cantidad * orden.cantidad
                    
                    lotes_mp = LoteMateriaPrima.objects.filter(
                        id_materia_prima=materia,
                        id_estado_lote_materia_prima=estado_disponible_mp
                    ).order_by('fecha_vencimiento')

                    for lote in lotes_mp:
                        if cantidad_a_descontar <= 0: break
                        
                        cantidad_tomada = min(lote.cantidad, cantidad_a_descontar)
                        
                        LoteProduccionMateria.objects.create(
                            id_lote_produccion=orden.id_lote_produccion,
                            id_lote_materia_prima=lote,
                            cantidad_usada=cantidad_tomada
                        )
                        
                        lote.cantidad -= cantidad_tomada
                        lote.save()
                        
                        cantidad_a_descontar -= cantidad_tomada
                
                print(f"Orden #{orden.id_orden_produccion} actualizada a 'Pendiente de inicio' y stock descontado.")

        except Receta.DoesNotExist:
            print(f"Advertencia: La orden #{orden.id_orden_produccion} no tiene receta asociada. Se omite.")
            continue

@transaction.atomic
def gestionar_reservas_para_orden_produccion(orden):
    """
    Orquesta la reserva de materias primas para una orden de producción.
    """

    estado_activa, _ = EstadoReservaMateria.objects.get_or_create(descripcion="Activa")
    estado_cancelada, _ = EstadoReservaMateria.objects.get_or_create(descripcion="Cancelada")

    # Cancelar reservas anteriores activas
    ReservaMateriaPrima.objects.filter(
        id_orden_produccion=orden,
        id_estado_reserva_materia=estado_activa
    ).update(id_estado_reserva_materia=estado_cancelada)

    # Buscar receta
    try:
        receta = Receta.objects.get(id_producto=orden.id_producto)
    except Receta.DoesNotExist:
        raise ValidationError({"error": f"No se encontró receta para el producto {orden.id_producto.nombre}"})

    ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
    estado_disponible = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")

    stock_completo = True

    for ingrediente in ingredientes:
        materia = ingrediente.id_materia_prima
        cantidad_necesaria = ingrediente.cantidad * orden.cantidad

        lotes_disponibles = LoteMateriaPrima.objects.filter(
            id_materia_prima=materia,
            id_estado_lote_materia_prima=estado_disponible
        ).order_by("fecha_vencimiento")

        cantidad_a_reservar = cantidad_necesaria
        total_stock = sum([l.cantidad_disponible for l in lotes_disponibles])

        if total_stock < cantidad_necesaria:
            stock_completo = False

        for lote in lotes_disponibles:
            if cantidad_a_reservar <= 0:
                break

            disponible = lote.cantidad_disponible
            if disponible <= 0:
                continue

            cantidad_reservada = min(cantidad_a_reservar, disponible)
            ReservaMateriaPrima.objects.create(
                id_orden_produccion=orden,
                id_lote_materia_prima=lote,
                cantidad_reservada=cantidad_reservada,
                id_estado_reserva_materia=estado_activa
            )
            cantidad_a_reservar -= cantidad_reservada

    # Actualizar estado de la orden
    if stock_completo:
        estado_final = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")
    else:
        estado_final = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")

    orden.id_estado_orden_produccion = estado_final
    orden.save()


@transaction.atomic
def descontar_stock_reservado(orden):
    """
    🔹 Descuenta definitivamente el stock reservado cuando la orden de producción se FINALIZA.
    🔹 Actualiza los lotes de materia prima y marca reservas como 'Consumidas'.
    🔹 Si un lote llega a 0, cambia su estado a 'Agotado'.
    """

    # --- Obtener estados necesarios ---
    try:
        estado_activa = EstadoReservaMateria.objects.get(descripcion__iexact="Activa")
        estado_consumida, _ = EstadoReservaMateria.objects.get_or_create(descripcion__iexact="Consumida")
        estado_agotado, _ = EstadoLoteMateriaPrima.objects.get_or_create(descripcion__iexact="Agotado")
    except EstadoReservaMateria.DoesNotExist:
        raise Exception("No se encontró el estado de reserva 'Activa'.")

    # --- Buscar reservas activas asociadas a la orden ---
    reservas = ReservaMateriaPrima.objects.filter(
        id_orden_produccion=orden,
        id_estado_reserva_materia=estado_activa
    ).select_related("id_lote_materia_prima")

    if not reservas.exists():
        print(f"⚠️ No hay reservas activas para la Orden #{orden.id_orden_produccion}")
        return

    print(f"🔹 Descontando stock de {reservas.count()} reservas para la Orden #{orden.id_orden_produccion}...")

    for reserva in reservas:
        lote = reserva.id_lote_materia_prima
        cantidad = reserva.cantidad_reservada

        print(f" → Lote {lote.id_lote_materia_prima} ({lote.id_materia_prima.nombre}): descontando {cantidad} unidades")

        # Verificar stock disponible
        if lote.cantidad < cantidad:
            raise Exception(
                f"Error: El lote {lote.id_lote_materia_prima} no tiene suficiente stock. "
                f"Disponible: {lote.cantidad}, Reservado: {cantidad}"
            )

        # Descontar del lote
        lote.cantidad -= cantidad
        if lote.cantidad <= 0:
            lote.id_estado_lote_materia_prima = estado_agotado
            lote.cantidad = 0  # nunca stock negativo
        lote.save()

        # Registrar en la tabla intermedia (trazabilidad)
        if orden.id_lote_produccion:
            LoteProduccionMateria.objects.create(
                id_lote_produccion=orden.id_lote_produccion,
                id_lote_materia_prima=lote,
                cantidad_usada=cantidad
            )

        # Marcar la reserva como consumida
        reserva.id_estado_reserva_materia = estado_consumida
        reserva.save()

    print(f"✅ Stock descontado correctamente para la Orden #{orden.id_orden_produccion}")