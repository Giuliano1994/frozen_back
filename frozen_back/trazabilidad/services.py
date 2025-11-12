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





def get_traceability_backward(id_orden_produccion):
    
    """
    Rastrea hacia atrás desde una Orden de Producción (OP) específica,
    incluyendo las Ordenes de Trabajo (OT), No Conformidades y Materias Primas.
    """
    
    op_report = {}
    try:
        # 1. PUNTO DE PARTIDA: La Orden de Producción
        orden_produccion = OrdenProduccion.objects.select_related(
            'id_supervisor', 
            'id_operario',
            'id_lote_produccion'
        ).get(pk=id_orden_produccion)

        lote = orden_produccion.id_lote_produccion

        if not lote:
            return {"error": f"La Orden de Producción {id_orden_produccion} no tiene Lote de Producción asociado."}


        op_report['orden_produccion'] = {
            'id_orden_produccion': orden_produccion.id_orden_produccion,
            'fecha_creacion': orden_produccion.fecha_creacion.isoformat(),
            'cantidad_planificada': orden_produccion.cantidad,
            'supervisor': orden_produccion.id_supervisor.nombre if orden_produccion.id_supervisor else 'N/A',
            'operario': orden_produccion.id_operario.nombre if orden_produccion.id_operario else 'N/A',
            'lote_asociado': lote.id_lote_produccion if lote else 'N/A',
            'ordenes_de_trabajo': [] # Se rellena a continuación
        }

        # 2. ORDENES DE TRABAJO (OT): Obtener la información de la línea y desperdicio
        ordenes_trabajo = OrdenDeTrabajo.objects.filter(
            id_orden_produccion=orden_produccion
        ).select_related(
            'id_linea_produccion', 
            'id_estado_orden_trabajo'
        ).prefetch_related(
            'no_conformidades__id_tipo_no_conformidad'
        )
        
        if ordenes_trabajo.exists():
            for ot in ordenes_trabajo:
                ot_data = {
                    'id_orden_trabajo': ot.id_orden_trabajo,
                    'linea_produccion': ot.id_linea_produccion.descripcion,
                    'estado': ot.id_estado_orden_trabajo.descripcion if ot.id_estado_orden_trabajo else 'N/A',
                    'cantidad_producida_neta': ot.cantidad_producida,
                    'inicio_real': ot.hora_inicio_real.isoformat() if ot.hora_inicio_real else 'N/A',
                    'fin_real': ot.hora_fin_real.isoformat() if ot.hora_fin_real else 'N/A',
                    'desperdicios_reportados': [
                        {
                            'tipo': nc.id_tipo_no_conformidad.nombre,
                            'cantidad_desperdiciada': nc.cant_desperdiciada
                        } 
                        for nc in ot.no_conformidades.all()
                    ]
                }
                op_report['orden_produccion']['ordenes_de_trabajo'].append(ot_data)
        else:
            op_report['orden_produccion']['ordenes_de_trabajo'] = [{'error': 'No se encontraron Órdenes de Trabajo asociadas a esta OP.'}]

        # 3. MATERIAS PRIMAS: ¿Qué ingredientes se usaron para este lote?
        mp_data = []
        if lote:
            # NOTA: Necesitas tener el modelo LoteProduccionMateria importado
            materias_usadas = LoteProduccionMateria.objects.filter(
                id_lote_produccion=lote
            ).select_related(
                'id_lote_materia_prima',
                'id_lote_materia_prima__id_materia_prima',
                'id_lote_materia_prima__id_materia_prima__id_proveedor'
            )

            for mp_link in materias_usadas:
                lote_mp = mp_link.id_lote_materia_prima
                materia_prima = lote_mp.id_materia_prima
                proveedor = materia_prima.id_proveedor
                
                mp_data.append({
                    'id_lote_materia_prima': lote_mp.id_lote_materia_prima,
                    'nombre_materia_prima': materia_prima.nombre,
                    'cantidad_usada': mp_link.cantidad_usada,
                    'proveedor': {'id_proveedor': proveedor.id_proveedor, 'nombre': proveedor.nombre}
                })
        
        op_report['materias_primas_usadas'] = mp_data
        
        return op_report

    except ObjectDoesNotExist:
        # Error específico de esta función
        return {"error": f"No se encontró la Orden de Producción con ID {id_orden_produccion}"}
    except Exception as e:
        return {"error": f"Error inesperado al rastrear la OP {id_orden_produccion}: {str(e)}"}




def get_traceability_for_order(id_orden_venta):
    """
    Realiza la trazabilidad HACIA ATRÁS para TODOS los productos 
    de una Orden de Venta completa, navegando a través de 
    OrdenVentaProducto -> OrdenProduccion -> OrdenDeTrabajo.
    """
    
    try:
        # 1. Validar la orden y obtener el cliente
        orden = OrdenVenta.objects.select_related('id_cliente').get(pk=id_orden_venta)
        
        # 2. Encontrar todas las líneas de producto para esta orden
        lineas_de_la_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden)

        if not lineas_de_la_orden.exists():
            return {"error": f"La orden de venta {id_orden_venta} existe pero no tiene productos."}

        # 3. Preparar el reporte principal
        full_report = {
            'consulta': {
                'tipo': 'Trazabilidad por Orden de Venta Completa',
                'id_orden_venta': orden.id_orden_venta,
            },
            'cliente': {
                'id_cliente': orden.id_cliente.id_cliente,
                'nombre': orden.id_cliente.nombre,
            },
            'productos_trazados': [] 
        }

        # 4. Iterar sobre CADA línea y buscar la OP asociada (LA LÓGICA CORREGIDA)
        for linea in lineas_de_la_orden:
            producto_report = {
                'id_orden_venta_producto': linea.id_orden_venta_producto,
                'producto': linea.id_producto.nombre if linea.id_producto else 'Desconocido',
                'cantidad_vendida': linea.cantidad,
                'ordenes_produccion': []
            }

            # Buscar las Ordenes de Producción (OP) asociadas a esta OrdenVenta y Producto
            ordenes_produccion_relacionadas = OrdenProduccion.objects.filter(
                id_orden_venta=orden,
                id_producto=linea.id_producto 
            ).order_by('-fecha_creacion') 
            
            if not ordenes_produccion_relacionadas.exists():
                producto_report['ordenes_produccion'].append({
                    'error': 'No se encontraron Órdenes de Producción para este producto en la venta.'
                })
            else:
                for op in ordenes_produccion_relacionadas:
                    # LLAMADA CORREGIDA: Usamos la nueva función auxiliar
                    trace_report_op = get_traceability_backward(op.id_orden_produccion)
                    
                    if 'error' in trace_report_op:
                        producto_report['ordenes_produccion'].append({'error': trace_report_op['error']})
                    else:
                        producto_report['ordenes_produccion'].append(trace_report_op['orden_produccion'])
                        producto_report['materias_primas_usadas'] = trace_report_op['materias_primas_usadas']
            
            full_report['productos_trazados'].append(producto_report)


        return full_report

    except OrdenVenta.DoesNotExist:
        return {"error": f"No se encontró la orden de venta con ID {id_orden_venta}"}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}






def get_traceability_forward(id_lote_materia_prima):
    """
    Realiza la trazabilidad HACIA ADELANTE (Forward Traceability).

    Comienza desde un lote específico de materia prima (ej. un lote de harina
    reportado como defectuoso) y rastrea hacia adelante para encontrar
    qué lotes de producto terminado se fabricaron con él y a qué clientes
    fueron entregados.

    Args:
        id_lote_materia_prima (int): El ID del lote de materia prima a investigar.

    Returns:
        dict: Un diccionario estructurado con todos los productos y clientes afectados.
              En caso de error, devuelve {"error": "mensaje..."}.
    """

    report = {}
    try:
        # 1. PUNTO DE PARTIDA: El lote de materia prima
        lote_mp = LoteMateriaPrima.objects.select_related(
            'id_materia_prima__id_proveedor'
        ).get(pk=id_lote_materia_prima)

        report['consulta'] = {
            'tipo': 'Trazabilidad Hacia Adelante',
            'id_lote_materia_prima': lote_mp.id_lote_materia_prima,
        }
        report['lote_materia_prima'] = {
            'nombre': lote_mp.id_materia_prima.nombre,
            'fecha_vencimiento': lote_mp.fecha_vencimiento,
        }
        report['proveedor'] = {
            'id_proveedor': lote_mp.id_materia_prima.id_proveedor.id_proveedor,
            'nombre': lote_mp.id_materia_prima.id_proveedor.nombre,
        }

        # 2. LOTES DE PRODUCCIÓN AFECTADOS: ¿Qué productos finales usaron este lote?
        lotes_prod_links = LoteProduccionMateria.objects.filter(
            id_lote_materia_prima=lote_mp
        ).select_related(
            'id_lote_produccion',
            'id_lote_produccion__id_producto'
        )

        if not lotes_prod_links.exists():
            report['lotes_produccion_afectados'] = []
            report['mensaje'] = "Este lote de materia prima no se ha utilizado en ninguna producción."
            return report

        lotes_afectados_data = []
        for link in lotes_prod_links:
            lote_prod = link.id_lote_produccion
            lote_data = {
                'id_lote_produccion': lote_prod.id_lote_produccion,
                'producto_nombre': lote_prod.id_producto.nombre,
                'fecha_produccion': lote_prod.fecha_produccion,
                'fecha_vencimiento': lote_prod.fecha_vencimiento,
                'cantidad_usada_en_lote': link.cantidad_usada,
                'clientes_afectados': [] # Se rellenará a continuación
            }

            # 3. CLIENTES AFECTADOS: ¿A quién se le entregaron esos lotes de producción?
            reservas = ReservaStock.objects.filter(
                id_lote_produccion=lote_prod,
                id_estado_reserva__descripcion='Activa' # O el estado que uses para 'Entregado'
            ).select_related(
                'id_orden_venta_producto__id_orden_venta',
                'id_orden_venta_producto__id_orden_venta__id_cliente'
            )

            clientes_data = []
            for reserva in reservas:
                ovp = reserva.id_orden_venta_producto
                orden = ovp.id_orden_venta
                cliente = orden.id_cliente
                
                clientes_data.append({
                    'id_cliente': cliente.id_cliente,
                    'nombre_cliente': cliente.nombre,
                    'id_orden_venta': orden.id_orden_venta,
                    'fecha_orden': orden.fecha,
                    'cantidad_entregada': reserva.cantidad_reservada
                })
            
            # Agregamos solo si se encontraron clientes
            if clientes_data:
                lote_data['clientes_afectados'] = clientes_data
                lotes_afectados_data.append(lote_data)

        report['lotes_produccion_afectados'] = lotes_afectados_data
        return report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró el lote de materia prima con ID {id_lote_materia_prima}"}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}
    





    