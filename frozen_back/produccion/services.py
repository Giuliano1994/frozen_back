
from django.db import transaction, models
from django.db.models import Sum
from .models import OrdenProduccion, EstadoOrdenProduccion, NoConformidad, OrdenProduccion
from stock.models import LoteMateriaPrima, EstadoLoteMateriaPrima, LoteProduccionMateria, ReservaMateriaPrima, EstadoReservaMateria
from recetas.models import Receta, RecetaMateriaPrima
from django.core.exceptions import ValidationError
from recetas.models import Receta, RecetaMateriaPrima
from stock.services import verificar_stock_mp_y_enviar_alerta
from compras.models import OrdenCompra, OrdenCompraMateriaPrima, OrdenCompraProduccion, EstadoOrdenCompra
from django.utils import timezone
from materias_primas.models import MateriaPrima
from collections import defaultdict
import math

@transaction.atomic
def procesar_ordenes_en_espera(materia_prima_ingresada):
    """
    Busca órdenes de producción 'En espera' que necesiten la materia prima que acaba de ingresar.
    Si ahora tienen stock suficiente para TODOS sus ingredientes, las pasa a 'Pendiente de inicio'
    creando RESERVAS en lugar de descontar directamente.
    """
    print(f"Iniciando revisión de órdenes en espera por ingreso de: {materia_prima_ingresada.nombre}")

    # 1. Obtener los estados que vamos a necesitar
    try:
        estado_en_espera = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")
        estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")
        estado_disponible_mp = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")
        estado_activa_reserva = EstadoReservaMateria.objects.get(descripcion__iexact="Activa")
    except (EstadoOrdenProduccion.DoesNotExist, EstadoLoteMateriaPrima.DoesNotExist, EstadoReservaMateria.DoesNotExist) as e:
        print(f"Error: No se encontraron los estados necesarios en la BBDD. {e}")
        return

    # 2. Encontrar órdenes 'En espera' que usen esta materia prima en su receta
    ordenes_a_revisar = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_en_espera,
        id_producto__receta__recetamateriaprima__id_materia_prima=materia_prima_ingresada
    ).distinct().order_by('fecha_creacion')  # Ordenar por más antigua primero

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
            # Verificar stock DISPONIBLE (considerando reservas existentes)
            for ingrediente in ingredientes:
                materia = ingrediente.id_materia_prima
                cantidad_necesaria = ingrediente.cantidad * orden.cantidad
                
                # 🔹 CALCULAR: Cuánto ya tenemos reservado vs cuánto nos falta
                reservas_existentes = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=orden,
                    id_estado_reserva_materia=estado_activa_reserva,
                    id_lote_materia_prima__id_materia_prima=materia
                ).aggregate(total_reservado=Sum('cantidad_reservada'))['total_reservado'] or 0
                
                cantidad_faltante = max(0, cantidad_necesaria - reservas_existentes)
                
                if cantidad_faltante > 0:
                    # Calcular stock disponible para completar lo que falta
                    lotes_disponibles = LoteMateriaPrima.objects.filter(
                        id_materia_prima=materia,
                        id_estado_lote_materia_prima=estado_disponible_mp
                    )
                    stock_disponible_total = 0

                    for lote in lotes_disponibles:
                        stock_disponible_total += lote.cantidad_disponible

                    if stock_disponible_total < cantidad_faltante:
                        stock_suficiente = False
                        print(f"Falta stock disponible para {materia.nombre}. Ya reservado: {reservas_existentes}, Faltante: {cantidad_faltante}, Disponible: {stock_disponible_total}.")
                        break
                    else:
                        print(f"✅ {materia.nombre}: Ya reservado: {reservas_existentes}, Faltante: {cantidad_faltante}, Disponible: {stock_disponible_total}")
                else:
                    print(f"✅ {materia.nombre}: Ya completamente reservado ({reservas_existentes}/{cantidad_necesaria})")

            # 4. Si hay stock para completar lo faltante, crear RESERVAS adicionales
            if stock_suficiente:
                print(f"¡Stock suficiente para completar la Orden #{orden.id_orden_produccion}! Creando/actualizando reservas...")
                
                reservas_creadas = 0
                # Completar reservas para cada ingrediente que lo necesite
                for ingrediente in ingredientes:
                    materia = ingrediente.id_materia_prima
                    cantidad_necesaria = ingrediente.cantidad * orden.cantidad
                    
                    # Calcular cuánto ya está reservado y cuánto falta
                    reservas_existentes = ReservaMateriaPrima.objects.filter(
                        id_orden_produccion=orden,
                        id_estado_reserva_materia=estado_activa_reserva,
                        id_lote_materia_prima__id_materia_prima=materia
                    ).aggregate(total_reservado=Sum('cantidad_reservada'))['total_reservado'] or 0
                    
                    cantidad_faltante = max(0, cantidad_necesaria - reservas_existentes)
                    
                    if cantidad_faltante > 0:
                        print(f"  Completando reserva para {materia.nombre}: faltan {cantidad_faltante} unidades")
                        
                        lotes_mp = LoteMateriaPrima.objects.filter(
                            id_materia_prima=materia,
                            id_estado_lote_materia_prima=estado_disponible_mp
                        ).order_by('fecha_vencimiento')

                        cantidad_a_reservar = cantidad_faltante

                        for lote in lotes_mp:
                            if cantidad_a_reservar <= 0: 
                                break
                            
                            disponible_lote = lote.cantidad_disponible
                            if disponible_lote <= 0:
                                continue
                                
                            cantidad_reservada = min(disponible_lote, cantidad_a_reservar)
                            
                            # Crear nueva reserva para completar lo faltante
                            ReservaMateriaPrima.objects.create(
                                id_orden_produccion=orden,
                                id_lote_materia_prima=lote,
                                cantidad_reservada=cantidad_reservada,
                                id_estado_reserva_materia=estado_activa_reserva
                            )
                            
                            cantidad_a_reservar -= cantidad_reservada
                            reservas_creadas += 1
                            print(f"    → Reservados {cantidad_reservada} de {materia.nombre} (Lote: {lote.id_lote_materia_prima})")
                
                # Cambiar estado de la orden
                orden.id_estado_orden_produccion = estado_pendiente
                orden.save()
                
                print(f"✅ Orden #{orden.id_orden_produccion} actualizada a 'Pendiente de inicio'. Reservas creadas: {reservas_creadas}")

            else:
                print(f"❌ Stock insuficiente para completar la Orden #{orden.id_orden_produccion}. Permanece en espera.")

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

    # Recolectar faltantes por proveedor para agrupar pedidos
    faltantes_por_proveedor = defaultdict(list)  # proveedor -> list of (materia, faltante)

    for ingrediente in ingredientes:
        materia = ingrediente.id_materia_prima
        cantidad_necesaria = ingrediente.cantidad * orden.cantidad

        lotes_disponibles = LoteMateriaPrima.objects.filter(
            id_materia_prima=materia,
            id_estado_lote_materia_prima=estado_disponible
        ).order_by("fecha_vencimiento")

        total_stock = sum([l.cantidad_disponible for l in lotes_disponibles])

        if total_stock < cantidad_necesaria:
            stock_completo = False
            faltante_para_mp = cantidad_necesaria - total_stock
            proveedor = materia.id_proveedor
            faltantes_por_proveedor[proveedor].append((materia, faltante_para_mp))

        # Crear reservas disponibles (hasta la cantidad necesaria)
        cantidad_a_reservar = cantidad_necesaria
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

    # Crear órdenes de compra agrupadas por proveedor para los faltantes
    if faltantes_por_proveedor:
        try:
            estado_proceso, _ = EstadoOrdenCompra.objects.get_or_create(descripcion__iexact="En proceso")
        except Exception:
            estado_proceso = None

        for proveedor, items in faltantes_por_proveedor.items():
            try:
                fecha_solicitud = timezone.now().date()
                fecha_entrega_estimada = fecha_solicitud + timezone.timedelta(days=(proveedor.lead_time_days or 0))

                orden_compra = OrdenCompra.objects.create(
                    id_estado_orden_compra=estado_proceso,
                    id_proveedor=proveedor,
                    fecha_solicitud=fecha_solicitud,
                    fecha_entrega_estimada=fecha_entrega_estimada
                )

                for materia, faltante in items:
                    cantidad_pedido = max(faltante, materia.cantidad_minima_pedido or 1)
                    OrdenCompraMateriaPrima.objects.create(
                        id_orden_compra=orden_compra,
                        id_materia_prima=materia,
                        cantidad=cantidad_pedido
                    )

                OrdenCompraProduccion.objects.create(
                    id_orden_compra=orden_compra,
                    id_orden_produccion=orden
                )

                print(f"Se creó OrdenCompra #{orden_compra.id_orden_compra} para proveedor '{proveedor.nombre}' con {len(items)} items asociada a OrdenProduccion #{orden.id_orden_produccion}")
            except Exception as e:
                print(f"Error al crear orden de compra agrupada para proveedor {getattr(proveedor,'nombre',proveedor)}: {e}")

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

    try:
        estado_activa = EstadoReservaMateria.objects.get(descripcion__iexact="Activa")
        estado_consumida, _ = EstadoReservaMateria.objects.get_or_create(descripcion__iexact="Consumida")
        estado_agotado, _ = EstadoLoteMateriaPrima.objects.get_or_create(descripcion__iexact="Agotado")
    except EstadoReservaMateria.DoesNotExist:
        raise Exception("No se encontró el estado de reserva 'Activa'.")

    # Buscar reservas activas asociadas a la orden
    reservas = (
        ReservaMateriaPrima.objects
        .filter(id_orden_produccion=orden, id_estado_reserva_materia=estado_activa)
        .select_related("id_lote_materia_prima", "id_lote_materia_prima__id_materia_prima")
    )

    if not reservas.exists():
        print(f"⚠️ No hay reservas activas para la Orden #{orden.id_orden_produccion}")
        return

    print(f"🔹 Descontando stock de {reservas.count()} reservas para la Orden #{orden.id_orden_produccion}...")

    materias_primas_afectadas = set()

    for reserva in reservas:
        lote = reserva.id_lote_materia_prima
        cantidad = reserva.cantidad_reservada

        print(f" → Lote {lote.id_lote_materia_prima} ({lote.id_materia_prima.nombre}): descontando {cantidad} unidades")

        # Validar stock suficiente
        if lote.cantidad < cantidad:
            raise Exception(
                f"Error: Lote {lote.id_lote_materia_prima} no tiene suficiente stock. "
                f"Disponible: {lote.cantidad}, Reservado: {cantidad}"
            )

        # Descontar del stock físico
        lote.cantidad -= cantidad
        if lote.cantidad <= 0:
            lote.cantidad = 0
            lote.id_estado_lote_materia_prima = estado_agotado
        lote.save()

        materias_primas_afectadas.add(lote.id_materia_prima.pk)

        # Registrar trazabilidad
        if orden.id_lote_produccion:
            LoteProduccionMateria.objects.create(
                id_lote_produccion=orden.id_lote_produccion,
                id_lote_materia_prima=lote,
                cantidad_usada=cantidad
            )

        # Cambiar el estado de la reserva
        reserva.id_estado_reserva_materia = estado_consumida
        reserva.save()

    print(f"✅ Stock descontado correctamente para la Orden #{orden.id_orden_produccion}")


    print(f"Verificando umbrales de stock para {len(materias_primas_afectadas)} materias primas...")
    for mp_id in materias_primas_afectadas:
        verificar_stock_mp_y_enviar_alerta(mp_id)





def calcular_porcentaje_desperdicio_historico(id_producto: int) -> float:
    """
    Calcula el porcentaje de desperdicio promedio basado en las últimas 10
    órdenes de producción finalizadas para un producto.

    Retorna solo el porcentaje de desperdicio (como un float, ej: 10.5).
    """
    try:
        # Busca el estado 'Finalizada'
        estado_finalizada = EstadoOrdenProduccion.objects.get(descripcion__iexact="Finalizada")
    except EstadoOrdenProduccion.DoesNotExist:
        print("Advertencia: No se encontró el estado 'Finalizada'. No se puede calcular desperdicio.")
        return 0.0 # Devolver 0% si no podemos calcular

    # Obtener las últimas 10 órdenes de producción finalizadas para ese producto
    ultimas_ops_finalizadas = OrdenProduccion.objects.filter(
        id_producto_id=id_producto,
        id_estado_orden_produccion=estado_finalizada
    ).order_by('-fecha_creacion')[:10]

    if not ultimas_ops_finalizadas:
        print(f"No hay historial de OPs finalizadas para producto {id_producto}. No se puede calcular desperdicio.")
        return 0.0

    # Calcular el total producido y desperdiciado en esas órdenes
    total_producido_historico = 0
    total_desperdiciado_historico = 0

    for op in ultimas_ops_finalizadas:
        total_producido_historico += op.cantidad
        desperdicio_op = NoConformidad.objects.filter(
            id_orden_produccion=op
        ).aggregate(total=models.Sum('cant_desperdiciada'))['total'] or 0
        total_desperdiciado_historico += desperdicio_op

    # Calcular el porcentaje de desperdicio promedio
    if total_producido_historico > 0:
        porcentaje_desperdicio = (total_desperdiciado_historico / total_producido_historico) * 100.0 # Usar 100.0 para resultado float
    else:
        porcentaje_desperdicio = 0.0

    return round(porcentaje_desperdicio, 2) # Devolver float redondeado