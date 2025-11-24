from django.db import models, transaction
from django.core.mail import send_mail
from productos.models import Producto
from .models import LoteProduccion, EstadoLoteProduccion, LoteMateriaPrima, EstadoLoteMateriaPrima, ReservaMateriaPrima, EstadoReservaMateria, ReservaStock
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Q
from django.db.models.functions import Coalesce
from django.conf import settings
import threading
import requests
from stock.models import ReservaStock
from produccion.models import OrdenProduccion, EstadoOrdenProduccion

def cantidad_total_producto(id_producto):
    """
    Devuelve la cantidad total disponible de un producto sumando
    los lotes en estado 'Disponible'.
    """
    total = (
        LoteProduccion.objects
        .filter(
            id_producto_id=id_producto,
            id_estado_lote_produccion__descripcion="Disponible"
        )
        .aggregate(total=Sum("cantidad"))
        .get("total") or 0
    )
    return total



def get_stock_disponible_todos_los_productos():
    """
    Devuelve un QuerySet con la cantidad total DISPONIBLE de cada producto.
    Calcula el stock basándose en lotes 'Disponibles' y reservas 'Activas'.
    """
    
    # 1. Filtro para sumar solo la cantidad de lotes 'Disponibles'
    filtro_lotes_disponibles = Q(
        loteproduccion__id_estado_lote_produccion__descripcion="Disponible"
    )
    
    # 2. Filtro para sumar solo la cantidad reservada de reservas 'Activas'
    #    que pertenezcan a lotes 'Disponibles'.
    filtro_reservas_activas = (
        Q(loteproduccion__id_estado_lote_produccion__descripcion="Disponible") &
        Q(loteproduccion__reservas__id_estado_reserva__descripcion='Activa')
    )

    # 3. Consultamos desde Producto y anotamos los totales
    productos_con_stock = Producto.objects.annotate(
        # Suma total de 'cantidad' de todos sus lotes 'Disponibles'
        total_producido=Coalesce(
            Sum('loteproduccion__cantidad', filter=filtro_lotes_disponibles), 
            0
        ),
        # Suma total de 'cantidad_reservada' de sus reservas 'Activas'
        total_reservado=Coalesce(
            Sum('loteproduccion__reservas__cantidad_reservada', filter=filtro_reservas_activas), 
            0
        )
    ).annotate(
        # 4. Calculamos el disponible final para cada producto
        cantidad_disponible=F('total_producido') - F('total_reservado')
    )

    # 5. Devolvemos los campos que nos interesan
    #    (Añado 'nombre' porque es muy útil y no tiene costo de rendimiento aquí)
    return productos_con_stock.values(
        'id_producto', 
        'nombre', 
        'cantidad_disponible',
        'umbral_minimo',
        'descripcion'
    ).order_by('id_producto')



def get_stock_disponible_para_producto(id_producto):
    """
    Devuelve la cantidad total DISPONIBLE de un producto.
    Calcula el total reservado para cada lote sumando ÚNICAMENTE las reservas 'Activas'.
    """
    # 1. Creamos un filtro para las reservas activas que usaremos en la suma.
    filtro_reservas_activas = Q(reservas__id_estado_reserva__descripcion='Activa')

    # 2. Anotamos cada lote con la suma de sus reservas activas.
    lotes_con_reservas = LoteProduccion.objects.filter(
        id_producto_id=id_producto,
        id_estado_lote_produccion__descripcion="Disponible"
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    )

    # 3. Anotamos la cantidad disponible para cada lote.
    lotes_con_disponible = lotes_con_reservas.annotate(
        disponible=F('cantidad') - F('total_reservado')
    )

    # 4. Finalmente, sumamos el total de las cantidades disponibles de todos los lotes.
    resultado_agregado = lotes_con_disponible.aggregate(
        total=Sum('disponible')
    )

    total_disponible = resultado_agregado.get('total') or 0

    return total_disponible







def verificar_stock_y_enviar_alerta(id_producto):
    try:
        producto = Producto.objects.get(pk=id_producto)
    except Producto.DoesNotExist:
        return {"error": f"El producto con ID {id_producto} no existe."}

    total_disponible = get_stock_disponible_para_producto(id_producto)
    print("total disponible:", total_disponible)  # Línea de depuración
    umbral = producto.umbral_minimo
    print("umbral:", umbral)  # Línea de depuración
    alerta = total_disponible < umbral

    mensaje = (
        f"⚠️ Stock por debajo del umbral mínimo ({total_disponible} < {umbral})"
        if alerta else
        f"✅ Stock suficiente ({total_disponible} ≥ {umbral})"
    )

    # Si hay alerta, enviar ambas notificaciones en segundo plano
    if alerta:
        asunto_email = f"⚠️ Alerta de stock bajo - {producto.nombre}"
        cuerpo_notificacion = (
            f"Producto: {producto.nombre}\n"
            f"Cantidad disponible: {total_disponible}\n"
            f"Umbral mínimo: {umbral}\n\n"
            "Por favor, revisar el stock o generar nuevo lote de producción."
        )
        # 1. Enviar correo (tu código existente)
    #    _enviar_correo_async(asunto_email, cuerpo_notificacion, email)
        
        # 2. Enviar mensaje de Telegram (nueva llamada)
        _enviar_telegram_async(cuerpo_notificacion)

    return {
        "id_producto": id_producto,
        "nombre": producto.nombre,
        "cantidad_disponible": total_disponible,
        "umbral_minimo": umbral,
        "alerta": alerta,
        "mensaje": mensaje,
      #  "email_notificado": email if alerta else None
    }

def _enviar_correo_async(asunto, cuerpo, destinatario):
    """
    Envía un correo en un hilo aparte para no bloquear la vista.
    """
    threading.Thread(
        target=send_mail,
        args=(asunto, cuerpo, None, [destinatario]),
        kwargs={"fail_silently": False}
    ).start()



# --- NUEVA FUNCIÓN PARA TELEGRAM ---
def _enviar_telegram_async(mensaje):
    """
    Envía un mensaje de Telegram en un hilo aparte.
    """
    def send_request():
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        # Salir si no están configuradas las credenciales
        if not token or not chat_id:
            print("ADVERTENCIA: Credenciales de Telegram no configuradas en settings.py")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": mensaje,
            "parse_mode": "Markdown" # Opcional, para formato
        }
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()  # Lanza un error si la petición falla
        except requests.exceptions.RequestException as e:
            print(f"Error al enviar mensaje de Telegram: {e}")

    # Ejecutar el envío en un hilo separado
    threading.Thread(target=send_request).start()









# --- INICIO DE NUEVAS FUNCIONES PARA MATERIA PRIMA ---

def get_stock_disponible_para_materia_prima(id_materia_prima):
    """
    Devuelve la cantidad total DISPONIBLE de una materia prima.
    Calcula el total reservado para cada lote sumando ÚNICAMENTE las reservas 'Activas'.
    """
    
    # 1. Filtro para reservas activas (materias primas)
    filtro_reservas_activas = Q(reservas__id_estado_reserva_materia__descripcion='Activa')

    # 2. Anotamos cada lote de MP con la suma de sus reservas activas.
    lotes_con_reservas = LoteMateriaPrima.objects.filter(
        id_materia_prima_id=id_materia_prima,
        id_estado_lote_materia_prima__descripcion="disponible"
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    )

    # 3. Anotamos la cantidad disponible para cada lote (stock físico - reservado).
    lotes_con_disponible = lotes_con_reservas.annotate(
        disponible=F('cantidad') - F('total_reservado')
    )

    # 4. Finalmente, sumamos el total de las cantidades disponibles de todos los lotes.
    resultado_agregado = lotes_con_disponible.aggregate(
        total=Sum('disponible')
    )

    total_disponible = resultado_agregado.get('total') or 0

    return total_disponible


def verificar_stock_mp_y_enviar_alerta(id_materia_prima):
    """
    Verifica el stock de una materia prima contra su umbral mínimo
    y envía una alerta por Telegram si está por debajo.
    """
    try:
        materia_prima = MateriaPrima.objects.get(pk=id_materia_prima)
    except MateriaPrima.DoesNotExist:
        print(f"Error: La materia prima con ID {id_materia_prima} no existe.")
        return

    total_disponible = get_stock_disponible_para_materia_prima(id_materia_prima)
    umbral = materia_prima.umbral_minimo
    
    print(f"Verificando stock MP {materia_prima.nombre}: Disponible={total_disponible}, Umbral={umbral}")

    if total_disponible < umbral:
        # Formatear el mensaje para Telegram
        asunto_email = f"⚠️ Alerta de stock bajo - {materia_prima.nombre}"
        cuerpo_notificacion = (
            f"*{asunto_email}*\n\n"  # Título en negrita para Telegram
            f"Materia Prima: {materia_prima.nombre}\n"
            f"Cantidad disponible: *{total_disponible}*\n"
            f"Umbral mínimo: *{umbral}*\n\n"
            "Por favor, contactar al proveedor o revisar compras."
        )
        
        # Enviar mensaje de Telegram
        _enviar_telegram_async(cuerpo_notificacion)
        
        print(f"¡ALERTA DE STOCK BAJO enviada para {materia_prima.nombre}!")

# --- FIN DE NUEVAS FUNCIONES ---
    



def actualizar_estado_lote_producto(lote_produccion, nuevo_estado):
    """
    Servicio centralizado para cambiar estado de un Lote de Producto.
    1. Actualiza el lote.
    2. Si es Cuarentena:
       - Borra reservas de ventas (Producto Terminado).
       - Borra reservas de Materia Prima de la OP asociada.
    3. Sincroniza la Orden de Producción asociada.
    """
    mensajes = []
    
    # 1. Actualizar el Lote
    lote_produccion.id_estado_lote_produccion = nuevo_estado
    lote_produccion.save()

    # Buscamos la OP asociada (la necesitamos para limpiar MP y para cambiar su estado)
    op_asociada = OrdenProduccion.objects.filter(id_lote_produccion=lote_produccion).first()

    # ===================================================================
    # 🛡️ Lógica de CUARENTENA (Limpieza Profunda)
    # ===================================================================
    if nuevo_estado.descripcion.lower() == "cuarentena":
        
        # A. Limpiar Reservas de VENTAS (Producto Terminado)
        reservas_activas_pt = ReservaStock.objects.filter(
            id_lote_produccion=lote_produccion,
            id_estado_reserva__descripcion="Activa"
        )
        cantidad_pt = reservas_activas_pt.count()
        
        if cantidad_pt > 0:
            ovs_ids = list(reservas_activas_pt.values_list('id_orden_venta_producto__id_orden_venta_id', flat=True))
            reservas_activas_pt.delete()
            msg_pt = f"⚠️ Lote Prod {lote_produccion.pk} a Cuarentena: Se borraron {cantidad_pt} reservas de Venta (OVs: {ovs_ids})."
            mensajes.append(msg_pt)
            print(msg_pt)

        # B. Limpiar Reservas de MATERIA PRIMA (Orden de Producción) - NUEVO
        if op_asociada:
            reservas_activas_mp = ReservaMateriaPrima.objects.filter(
                id_orden_produccion=op_asociada
                # id_estado_reserva_materia__descripcion="Activa" # Descomentar si usas estados en reservas MP
            )
            cantidad_mp = reservas_activas_mp.count()

            if cantidad_mp > 0:
                reservas_activas_mp.delete()
                msg_mp = f"☢️ OP #{op_asociada.pk} a Cuarentena: Se liberaron {cantidad_mp} reservas de Materia Prima."
                mensajes.append(msg_mp)
                print(msg_mp)

    # ===================================================================

    # 3. Sincronizar Estado de la OP
    if op_asociada:
        try:
            estado_equiv_op = EstadoOrdenProduccion.objects.get(descripcion__iexact=nuevo_estado.descripcion)
            
            if op_asociada.id_estado_orden_produccion != estado_equiv_op:
                op_asociada.id_estado_orden_produccion = estado_equiv_op
                op_asociada.save()
                mensajes.append(f"OP #{op_asociada.pk} cambiada a estado '{estado_equiv_op.descripcion}'.")
        except EstadoOrdenProduccion.DoesNotExist:
            pass 

    return mensajes