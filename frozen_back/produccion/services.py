
from django.db import transaction, models
from django.db.models import Sum, Q
from .models import OrdenProduccion, EstadoOrdenProduccion, OrdenProduccion
from stock.models import LoteMateriaPrima, EstadoLoteMateriaPrima, LoteProduccionMateria, ReservaMateriaPrima, EstadoReservaMateria
from recetas.models import Receta, RecetaMateriaPrima
from django.core.exceptions import ValidationError
from recetas.models import Receta, RecetaMateriaPrima
from stock.services import verificar_stock_mp_y_enviar_alerta

from stock.models import EstadoLoteProduccion


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








def calcular_porcentaje_desperdicio_historico(id_producto: int, from_date=None, limit=10) -> float:
    """
    Calcula el porcentaje histórico de desperdicio usando ORDENES DE TRABAJO,
    no órdenes de producción.

    Ahora soporta:
    ✅ Filtrar desde una fecha específica
    ✅ Especificar cuántas OP analizar (limit)
    """

    try:
        estado_finalizada = EstadoOrdenProduccion.objects.get(descripcion__iexact="Finalizada")
    except EstadoOrdenProduccion.DoesNotExist:
        return 0.0

    # ----- 1. Buscar OP finalizadas del producto -----
    qs = OrdenProduccion.objects.filter(
        id_producto_id=id_producto,
        id_estado_orden_produccion=estado_finalizada
    )

    if from_date:
        qs = qs.filter(fecha_creacion__date__gte=from_date)

    # Aplicar límite
    ops = qs.order_by("-fecha_creacion")[:limit]

    if not ops:
        return 0.0

    # ----- 2. Calcular producción total y desperdicio total desde OTs -----
    total_producido = 0
    total_desperdicio = 0

    for op in ops:
        # Todas las OTs de la OP
        ots = op.ordenes_de_trabajo.all()

        # Sumar producción
        for ot in ots:
            # Si ya se finalizó, tomar la real; si no, tomar programada
            producido_ot = ot.cantidad_producida if ot.cantidad_producida is not None else ot.cantidad_programada
            total_producido += producido_ot

            # Sumar desperdicio de esta OT
            desperdicio_ot = ot.no_conformidades.aggregate(
                total=models.Sum("cant_desperdiciada")
            )["total"] or 0

            total_desperdicio += desperdicio_ot

    # ----- 3. Evitar división por cero -----
    if total_producido <= 0:
        return 0.0

    # ----- 4. Calcular porcentaje -----
    porcentaje = (total_desperdicio / total_producido) * 100.0
    return round(porcentaje, 2)







@transaction.atomic
def verificar_y_actualizar_op_segun_ots(orden_produccion_id):
    """
    (PASO 2: FINALIZACIÓN DE PRODUCCIÓN)
    Verifica las OTs de una OP. Si todas están en estado final,
    actualiza la OP a 'Finalizada', descuenta stock y ajusta el lote.
    
    Esta función se debe llamar cuando una OT se completa en la planta.
    """
    try:
        orden = OrdenProduccion.objects.get(id_orden_produccion=orden_produccion_id)
    except OrdenProduccion.DoesNotExist:
        print(f"Error: No se encontró la OP {orden_produccion_id} para verificar.")
        return

    # ❗️ CHEQUEO DE ESTADO:
    # Solo actuamos sobre OPs que el planificador ya marcó como 'Planificada'
    # o que ya están 'En proceso' (si las OTs se pueden completar en varios días)
    if orden.id_estado_orden_produccion.descripcion not in ["Planificada", "En proceso"]:
        print(f"Info: OP {orden.id_orden_produccion} no está 'Planificada' o 'En proceso'. El trigger de OT se ignora.")
        return

    # 1. Definir qué estados de OT cuentan como "finalizados"
    estados_finales_ot = Q(
        id_estado_orden_trabajo__descripcion__iexact='Completada'
    ) | Q(
        id_estado_orden_trabajo__descripcion__iexact='Cancelada'
    )

    # 2. Contar OTs (Asumiendo related_name='ordenes_de_trabajo')
    # ❗️ Si tu related_name es 'ordendetrabajo_set', cambia 'orden.ordenes_de_trabajo'
    try:
        total_ots = orden.ordenes_de_trabajo.count()
        ots_finalizadas = orden.ordenes_de_trabajo.filter(estados_finales_ot).count()
    except AttributeError:
        print(f"Error: 'related_name' para OTs en OP no es 'ordenes_de_trabajo'. Ajustar el código.")
        return

    # 3. Condición de finalización
    if total_ots > 0 and total_ots == ots_finalizadas:
        
        print(f"Todas las OTs para la OP {orden.id_orden_produccion} están finalizadas. Actualizando OP...")
        
        # 4. Obtener estados
        try:
            estado_op_finalizada = EstadoOrdenProduccion.objects.get(descripcion__iexact="Finalizada")
            estado_lote_disponible = EstadoLoteProduccion.objects.get(descripcion__iexact="Disponible")
        except (EstadoOrdenProduccion.DoesNotExist, EstadoLoteProduccion.DoesNotExist) as e:
            print(f"Error: No se encontró estado 'Finalizada' o 'Disponible'. {e}")
            raise ValidationError(f"Estados 'Finalizada'/'Disponible' no configurados: {e}")

        # 5. LÓGICA DE FINALIZACIÓN
        
        # 5.1. Descontar stock reservado (Consumo de MP)
        try:
            # ❗️ Debes implementar esta función
            # descontar_stock_reservado(orden) 
            pass # Placeholder
            print(f"Descontando stock de MP para OP {orden.id_orden_produccion}...")
        except Exception as e:
            print(f"Error al descontar stock para OP {orden.id_orden_produccion}: {e}")
            raise ValidationError(f"Error descontando stock: {e}")

        # 5.2. Actualizar Lote de Producción (Ingreso de PT)
        if orden.id_lote_produccion:
            lote = orden.id_lote_produccion
            
            # Suma la 'cantidad_producida' (real) solo de OTs 'Completadas'
            total_producido_real = orden.ordenes_de_trabajo.filter(
                id_estado_orden_trabajo__descripcion__iexact='Completada'
            ).aggregate(
                total=Sum('cantidad_producida')
            )['total'] or 0
            
            lote.cantidad = total_producido_real
            lote.id_estado_lote_produccion = estado_lote_disponible
            lote.save()
            
            # Actualiza la cantidad de la OP a la real producida
            orden.cantidad = total_producido_real
            
            print(f"Lote {lote.id_lote_produccion} actualizado. Cantidad final: {total_producido_real}")

        # 5.3. Actualizar estado de la OP
        orden.id_estado_orden_produccion = estado_op_finalizada
        orden.save()
        
        print(f"✅ OP {orden.id_orden_produccion} marcada como 'Finalizada'.")

    else:
        print(f"OP {orden.id_orden_produccion}: {ots_finalizadas}/{total_ots} OTs finalizadas. Aún no se completa (sigue 'Planificada' o 'En proceso').")












