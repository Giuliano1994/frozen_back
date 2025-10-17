from django.db import models, transaction
from django.core.mail import send_mail
from productos.models import Producto
from .models import LoteProduccion, EstadoLoteProduccion
from django.db.models import Sum, F, Q
from django.db.models.functions import Coalesce
from django.conf import settings
import threading
import requests

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



# --- NUEVA FUNCIÓN REUTILIZABLE ---
def verificar_stock_para_orden_venta(orden_venta):
    """
    Verifica si hay stock disponible para todos los productos de una orden de venta.
    Devuelve True si hay stock para todo, False en caso contrario.
    """
    from ventas.models import OrdenVentaProducto # Importación local para evitar importación circular
    
    productos_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    
    if not productos_orden.exists():
        return True # Una orden sin productos no tiene problemas de stock

    for item in productos_orden:
        disponible = get_stock_disponible_para_producto(item.id_producto.pk)
        if disponible < item.cantidad:
            print(f"Stock insuficiente para {item.id_producto.nombre}. Necesario: {item.cantidad}, Disponible: {disponible}")
            return False # Si falta stock para un producto, paramos y devolvemos False
    
    return True # Si el bucle termina, hay stock para todos

# --- NUEVA FUNCIÓN REUTILIZABLE ---
@transaction.atomic
def descontar_stock_para_orden_venta(orden_venta):
    """
    Descuenta del stock la cantidad de productos de una orden de venta.
    Usa una estrategia FIFO (primero los lotes que vencen antes).
    Esta función asume que el stock ya fue verificado.
    """
    from ventas.models import OrdenVentaProducto # Importación local
    
    productos_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden_venta)
    estado_disponible = EstadoLoteProduccion.objects.get(descripcion="Disponible")
    estado_agotado, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Agotado")

    for item in productos_orden:
        cantidad_a_descontar = item.cantidad
        lotes = LoteProduccion.objects.filter(
            id_producto=item.id_producto,
            id_estado_lote_produccion=estado_disponible,
            cantidad__gt=0
        ).order_by("fecha_vencimiento")

        for lote in lotes:
            if cantidad_a_descontar <= 0:
                break
            
            cantidad_tomada = min(lote.cantidad, cantidad_a_descontar)
            
            lote.cantidad -= cantidad_tomada
            cantidad_a_descontar -= cantidad_tomada
            
            if lote.cantidad == 0:
                lote.id_estado_lote_produccion = estado_agotado
            
            lote.save()

       
        # Después de actualizar los lotes para este producto, llamamos a la función de alerta.
        verificar_stock_y_enviar_alerta(item.id_producto.pk)


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