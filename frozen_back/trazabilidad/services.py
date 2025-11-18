"""
Servicios de Trazabilidad

Este módulo contiene la lógica de negocio para rastrear el ciclo de vida
completo de un producto, desde la materia prima hasta la entrega al cliente.
"""

# --- Imports de Django ---
from django.core.exceptions import ObjectDoesNotExist

# --- Imports de Modelos (organizados por app) ---
from ventas.models import OrdenVentaProducto
from stock.models import ReservaStock, LoteProduccionMateria, LoteMateriaPrima
from ventas.models import OrdenVenta, OrdenVentaProducto
from produccion.models import OrdenDeTrabajo, OrdenProduccion, NoConformidad
# (No necesitamos importar todos los modelos, solo los puntos de entrada 
# y los que usamos para select_related)





from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q

# Asegúrate de importar los modelos necesarios
from ventas.models import OrdenVenta, OrdenVentaProducto
from produccion.models import OrdenProduccion, OrdenProduccionPegging, OrdenDeTrabajo
from stock.models import ReservaStock, ReservaMateriaPrima, LoteProduccionMateria, LoteProduccion, LoteMateriaPrima

def get_traceability_for_order(id_orden_venta):
    """
    Realiza la trazabilidad HACIA ATRÁS para una Orden de Venta.
    
    Ahora es HÍBRIDA:
    1. Busca Stock Físico asignado (ReservaStock).
    2. Busca Producción en Curso asignada (OrdenProduccionPegging - MTO).
    """
    try:
        orden = OrdenVenta.objects.select_related('id_cliente').get(pk=id_orden_venta)
        full_report = {
            'id_orden_venta': orden.id_orden_venta,
            'cliente': {'id_cliente': orden.id_cliente.id_cliente, 'nombre': orden.id_cliente.nombre},
            'fecha_entrega': orden.fecha_entrega,
            'productos_trazados': []
        }

        # Iterar sobre las líneas de la orden de venta
        lineas_de_la_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden)

        for linea in lineas_de_la_orden:
            producto_report = {
                'producto': linea.id_producto.nombre if linea.id_producto else 'Desconocido',
                'cantidad_vendida': linea.cantidad,
                'origen': [] # Lista mixta (Stock o Producción)
            }
            
            # A. BUSCAR EN STOCK (Ya reservado/Entregado)
            reservas_stock = ReservaStock.objects.filter(
                id_orden_venta_producto=linea
            ).select_related('id_lote_produccion')

            for res in reservas_stock:
                lote = res.id_lote_produccion
                producto_report['origen'].append({
                    'tipo': 'STOCK_EXISTENTE',
                    'id_lote_pt': lote.id_lote_produccion,
                    'cantidad': res.cantidad_reservada,
                    'estado_reserva': res.id_estado_reserva.descripcion,
                    'fecha_vencimiento': lote.fecha_vencimiento,
                    # Trazamos la MP de este lote
                    'composicion_mp': get_mp_trace_for_lote(lote.id_lote_produccion)
                })

            # B. BUSCAR EN PRODUCCIÓN (MTO / Pegging)
            # Esto es nuevo con tu planificador: La OV está vinculada directamente a una OP
            peggings = OrdenProduccionPegging.objects.filter(
                id_orden_venta_producto=linea
            ).select_related('id_orden_produccion', 'id_orden_produccion__id_lote_produccion')

            for peg in peggings:
                op = peg.id_orden_produccion
                lote_pt_id = op.id_lote_produccion.id_lote_produccion if op.id_lote_produccion else None
                
                producto_report['origen'].append({
                    'tipo': 'PRODUCCION_EN_CURSO (MTO)',
                    'id_orden_produccion': op.id_orden_produccion,
                    'estado_op': op.id_estado_orden_produccion.descripcion,
                    'id_lote_pt_proyectado': lote_pt_id,
                    'cantidad_asignada': peg.cantidad_asignada,
                    'fecha_planificada': op.fecha_planificada,
                    # Trazamos la MP reservada para esta OP
                    'composicion_mp': get_mp_trace_for_op(op.id_orden_produccion)
                })

            full_report['productos_trazados'].append(producto_report)
            
        return full_report

    except OrdenVenta.DoesNotExist:
        return {"error": f"No se encontró la orden de venta con ID {id_orden_venta}"}
    except Exception as e:
        return {"error": f"Error inesperado en trazabilidad hacia atrás: {str(e)}"}


def get_mp_trace_for_lote(id_lote_produccion):
    """
    Obtiene MP usada para un Lote YA CREADO.
    Intenta buscar primero por la OP asociada al lote y sus reservas.
    """
    mp_data = []
    try:
        # 1. Buscamos la OP que generó este lote
        op = OrdenProduccion.objects.filter(id_lote_produccion_id=id_lote_produccion).first()
        
        if op:
            return get_mp_trace_for_op(op.id_orden_produccion)
        else:
            # Fallback: Si no hay OP (carga de stock manual), buscamos en tabla histórica si existe
            # (Si usas LoteProduccionMateria para históricos)
            links = LoteProduccionMateria.objects.filter(id_lote_produccion_id=id_lote_produccion)
            for link in links:
                mp_data.append({
                    'fuente': 'HISTORICO',
                    'materia_prima': link.id_lote_materia_prima.id_materia_prima.nombre,
                    'lote_mp': link.id_lote_materia_prima.id_lote_materia_prima,
                    'proveedor': link.id_lote_materia_prima.id_materia_prima.id_proveedor.nombre,
                    'cantidad': link.cantidad_usada
                })
    except Exception as e:
        mp_data.append({'error': str(e)})
    return mp_data


def get_mp_trace_for_op(id_orden_produccion):
    """
    Obtiene la MP reservada/usada para una Orden de Producción.
    Esta es la función clave para tu nuevo planificador.
    """
    mp_data = []
    try:
        reservas_mp = ReservaMateriaPrima.objects.filter(
            id_orden_produccion_id=id_orden_produccion
        ).select_related(
            'id_lote_materia_prima', 
            'id_lote_materia_prima__id_materia_prima',
            'id_lote_materia_prima__id_materia_prima__id_proveedor'
        )

        for res in reservas_mp:
            lote_mp = res.id_lote_materia_prima
            mp = lote_mp.id_materia_prima
            
            mp_data.append({
                'materia_prima': mp.nombre,
                'id_lote_mp': lote_mp.id_lote_materia_prima,
                'proveedor': mp.id_proveedor.nombre,
                'cantidad_reservada': res.cantidad_reservada,
                'estado_reserva': res.id_estado_reserva_materia.descripcion,
                'vencimiento_mp': lote_mp.fecha_vencimiento
            })
    except Exception as e:
        mp_data.append({'error': str(e)})
    return mp_data


def get_traceability_forward(id_lote_materia_prima):
    """
    Realiza la trazabilidad HACIA ADELANTE (MP Lote -> OP -> PT -> Cliente).
    Detecta si la MP está en una OP que va dedicada a un Cliente (Pegging).
    """
    report = {}
    try:
        lote_mp = LoteMateriaPrima.objects.select_related(
            'id_materia_prima__id_proveedor'
        ).get(pk=id_lote_materia_prima)

        report['lote_materia_prima'] = {
            'id': lote_mp.id_lote_materia_prima,
            'nombre': lote_mp.id_materia_prima.nombre,
            'proveedor': lote_mp.id_materia_prima.id_proveedor.nombre,
            'fecha_ingreso': lote_mp.fecha_produccion # Asumiendo fecha prod como ingreso
        }
        report['uso_en_produccion'] = []

        # 1. Buscar en qué OPs está reservada/usada esta MP
        reservas_mp = ReservaMateriaPrima.objects.filter(
            id_lote_materia_prima=lote_mp
        ).select_related(
            'id_orden_produccion', 
            'id_orden_produccion__id_producto',
            'id_orden_produccion__id_lote_produccion'
        )

        for res in reservas_mp:
            op = res.id_orden_produccion
            uso_data = {
                'id_orden_produccion': op.id_orden_produccion,
                'producto_final': op.id_producto.nombre,
                'cantidad_mp_usada': res.cantidad_reservada,
                'estado_op': op.id_estado_orden_produccion.descripcion,
                'lote_pt_generado': op.id_lote_produccion.id_lote_produccion if op.id_lote_produccion else 'Pendiente',
                'destinos_finales': []
            }

            # 2. A. Verificar si esta OP tiene PEGGING (Destino directo MTO)
            peggings = OrdenProduccionPegging.objects.filter(
                id_orden_produccion=op
            ).select_related('id_orden_venta_producto__id_orden_venta__id_cliente')

            for peg in peggings:
                ov = peg.id_orden_venta_producto.id_orden_venta
                uso_data['destinos_finales'].append({
                    'tipo': 'PEDIDO_DIRECTO (MTO)',
                    'cliente': ov.id_cliente.nombre,
                    'orden_venta': ov.id_orden_venta,
                    'cantidad_asignada': peg.cantidad_asignada
                })

            # 2. B. Verificar si el Lote PT generado ya fue reservado (Destino MTS o stock final)
            if op.id_lote_produccion:
                reservas_pt = ReservaStock.objects.filter(
                    id_lote_produccion=op.id_lote_produccion
                ).select_related('id_orden_venta_producto__id_orden_venta__id_cliente')
                
                for res_pt in reservas_pt:
                    ov = res_pt.id_orden_venta_producto.id_orden_venta
                    uso_data['destinos_finales'].append({
                        'tipo': 'DESPACHO_STOCK (MTS)',
                        'cliente': ov.id_cliente.nombre,
                        'orden_venta': ov.id_orden_venta,
                        'cantidad_entregada': res_pt.cantidad_reservada
                    })

            report['uso_en_produccion'].append(uso_data)

        return report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró el lote de materia prima con ID {id_lote_materia_prima}"}
    except Exception as e:
        return {"error": f"Error en trazabilidad hacia adelante: {str(e)}"}


def get_traceability_backward_op(id_orden_produccion):
    """
    Rastrea una OP específica. 
    Muestra para QUIÉN se está haciendo (Pegging) y QUÉ está consumiendo (MP).
    """
    op_report = {}
    try:
        orden_produccion = OrdenProduccion.objects.select_related(
            'id_producto', 'id_estado_orden_produccion'
        ).get(pk=id_orden_produccion)

        op_report['orden_produccion'] = {
            'id': orden_produccion.id_orden_produccion,
            'producto': orden_produccion.id_producto.nombre,
            'cantidad': orden_produccion.cantidad,
            'estado': orden_produccion.id_estado_orden_produccion.descripcion,
            'fecha_planificada': orden_produccion.fecha_planificada
        }

        # 1. ¿Para quién es esta OP? (Pegging)
        peggings = OrdenProduccionPegging.objects.filter(
            id_orden_produccion=orden_produccion
        ).select_related('id_orden_venta_producto__id_orden_venta__id_cliente')

        op_report['destino_cliente'] = []
        if peggings.exists():
            for peg in peggings:
                ov = peg.id_orden_venta_producto.id_orden_venta
                op_report['destino_cliente'].append({
                    'cliente': ov.id_cliente.nombre,
                    'orden_venta': ov.id_orden_venta,
                    'cantidad_asignada': peg.cantidad_asignada
                })
        else:
            op_report['destino_cliente'].append("Stock General (Sin pedido vinculado)")

        # 2. ¿Qué está consumiendo? (MP)
        op_report['materias_primas'] = get_mp_trace_for_op(id_orden_produccion)
        
        return op_report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró la Orden de Producción {id_orden_produccion}"}