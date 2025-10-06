from django.core.mail import send_mail
from productos.models import Producto
from .models import LoteProduccion
from django.db.models import Sum
from django.conf import settings
import threading

def cantidad_total_disponible_producto(id_producto):
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


"""
def verificar_stock_y_enviar_alerta(id_producto, email):
   
   # Verifica el stock de un producto y envía un correo de alerta si está por debajo del umbral.
   # Devuelve un diccionario con el resultado.
   
    try:
        producto = Producto.objects.get(pk=id_producto)
    except Producto.DoesNotExist:
        return {"error": f"El producto con ID {id_producto} no existe."}

    total_disponible = cantidad_total_disponible_producto(id_producto)
    umbral = producto.umbral_minimo
    alerta = total_disponible < umbral

    mensaje = (
        f"⚠️ Stock por debajo del umbral mínimo ({total_disponible} < {umbral})"
        if alerta else
        f"✅ Stock suficiente ({total_disponible} ≥ {umbral})"
    )

    if alerta:
        asunto = f"⚠️ Alerta de stock bajo - {producto.nombre}"
        cuerpo = (
            f"Producto: {producto.nombre}\n"
            f"Cantidad disponible: {total_disponible}\n"
            f"Umbral mínimo: {umbral}\n\n"
            "Por favor, revisar el stock o generar nuevo lote de producción."
        )

        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

    return {
        "id_producto": id_producto,
        "nombre": producto.nombre,
        "cantidad_disponible": total_disponible,
        "umbral_minimo": umbral,
        "alerta": alerta,
        "mensaje": mensaje,
        "email_notificado": email if alerta else None
    }


"""

def verificar_stock_y_enviar_alerta(id_producto, email):
    try:
        producto = Producto.objects.get(pk=id_producto)
    except Producto.DoesNotExist:
        return {"error": f"El producto con ID {id_producto} no existe."}

    total_disponible = cantidad_total_disponible_producto(id_producto)
    umbral = producto.umbral_minimo
    alerta = total_disponible < umbral

    mensaje = (
        f"⚠️ Stock por debajo del umbral mínimo ({total_disponible} < {umbral})"
        if alerta else
        f"✅ Stock suficiente ({total_disponible} ≥ {umbral})"
    )

    # Si hay alerta, enviar correo en segundo plano
    if alerta:
        asunto = f"⚠️ Alerta de stock bajo - {producto.nombre}"
        cuerpo = (
            f"Producto: {producto.nombre}\n"
            f"Cantidad disponible: {total_disponible}\n"
            f"Umbral mínimo: {umbral}\n\n"
            "Por favor, revisar el stock o generar nuevo lote de producción."
        )
        _enviar_correo_async(asunto, cuerpo, email)

    return {
        "id_producto": id_producto,
        "nombre": producto.nombre,
        "cantidad_disponible": total_disponible,
        "umbral_minimo": umbral,
        "alerta": alerta,
        "mensaje": mensaje,
        "email_notificado": email if alerta else None
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