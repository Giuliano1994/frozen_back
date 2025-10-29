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
from produccion.models import OrdenProduccion, NoConformidad
# (No necesitamos importar todos los modelos, solo los puntos de entrada 
# y los que usamos para select_related)





def get_traceability_backward(id_orden_venta_producto):
    
    """
    Realiza la trazabilidad HACIA ATRÁS (Backward Traceability).

    Comienza desde un producto entregado a un cliente (OrdenVentaProducto)
    y rastrea hacia atrás para encontrar qué lotes de producción se usaron,
    quién los hizo, y qué lotes de materia prima se consumieron, 
    incluyendo sus proveedores.

    Args:
        id_orden_venta_producto (int): El ID del ítem específico en la orden de venta.

    Returns:
        dict: Un diccionario estructurado con todo el historial de trazabilidad.
              En caso de error, devuelve {"error": "mensaje..."}.
    """
    
    report = {}
    try:
        # 1. PUNTO DE PARTIDA: El producto vendido
        ovp = OrdenVentaProducto.objects.select_related(
            'id_orden_venta__id_cliente', 
            'id_producto'
        ).get(pk=id_orden_venta_producto)

        report['consulta'] = {
            'tipo': 'Trazabilidad Hacia Atrás',
            'id_orden_venta_producto': ovp.id_orden_venta_producto,
            'id_orden_venta': ovp.id_orden_venta_id,
        }
        report['cliente'] = {
            'id_cliente': ovp.id_orden_venta.id_cliente.id_cliente,
            'nombre': ovp.id_orden_venta.id_cliente.nombre,
        }
        report['producto_reclamado'] = {
            'id_producto': ovp.id_producto.id_producto,
            'nombre': ovp.id_producto.nombre,
            'cantidad': ovp.cantidad,
        }

        # 2. LOTES ENTREGADOS: ¿Qué lotes de producto terminado se usaron?
        # (Usando el related_name "reservas" de OrdenVentaProducto)
        reservas = ovp.reservas.filter(
            id_estado_reserva__descripcion='Activa' # O el estado que uses para 'Entregado'
        ).select_related(
            'id_lote_produccion'
        )
        
        if not reservas.exists():
            report['lotes_entregados'] = []
            report['mensaje'] = "No se encontraron lotes de producción reservados/entregados para este ítem."
            return report

        lotes_entregados_data = []
        for reserva in reservas:
            lote = reserva.id_lote_produccion
            lote_data = {
                'id_lote_produccion': lote.id_lote_produccion,
                'fecha_produccion': lote.fecha_produccion,
                'fecha_vencimiento': lote.fecha_vencimiento,
                'cantidad_entregada_de_lote': reserva.cantidad_reservada,
                'orden_produccion': None, # Se rellenará a continuación
                'materias_primas_usadas': [] # Se rellenará a continuación
            }

            # 3. ORDEN DE PRODUCCIÓN: ¿Quién, cuándo y cómo se hizo este lote?
            try:
                orden = OrdenProduccion.objects.select_related(
                    'id_supervisor', 
                    'id_operario',
                    'id_linea_produccion'
                ).get(id_lote_produccion=lote)
                
                lote_data['orden_produccion'] = {
                    'id_orden_produccion': orden.id_orden_produccion,
                    'fecha_inicio': orden.fecha_inicio,
                    'cantidad_planificada': orden.cantidad,
                    'supervisor': orden.id_supervisor.nombre if orden.id_supervisor else 'N/A',
                    'operario': orden.id_operario.nombre if orden.id_operario else 'N/A',
                    'linea': orden.id_linea_produccion.descripcion if orden.id_linea_produccion else 'N/A',
                }

                # 4. DESPERDICIO: ¿Hubo problemas en esa orden?
                desperdicios = NoConformidad.objects.filter(id_orden_produccion=orden)
                lote_data['orden_produccion']['desperdicios_reportados'] = [
                    {
                        'descripcion': d.descripcion,
                        'cantidad_desperdiciada': d.cant_desperdiciada
                    } for d in desperdicios
                ]

            except ObjectDoesNotExist:
                lote_data['orden_produccion'] = {'error': 'No se encontró la orden de producción asociada a este lote.'}


            # 5. MATERIAS PRIMAS: ¿Qué ingredientes se usaron para este lote?
            materias_usadas = LoteProduccionMateria.objects.filter(
                id_lote_produccion=lote
            ).select_related(
                'id_lote_materia_prima',
                'id_lote_materia_prima__id_materia_prima',
                'id_lote_materia_prima__id_materia_prima__id_proveedor'
            )

            mp_data = []
            for mp_link in materias_usadas:
                lote_mp = mp_link.id_lote_materia_prima
                materia_prima = lote_mp.id_materia_prima
                proveedor = materia_prima.id_proveedor
                
                mp_data.append({
                    'id_lote_materia_prima': lote_mp.id_lote_materia_prima,
                    'nombre_materia_prima': materia_prima.nombre,
                    'cantidad_usada': mp_link.cantidad_usada,
                    'fecha_vencimiento_mp': lote_mp.fecha_vencimiento,
                    'proveedor': {
                        'id_proveedor': proveedor.id_proveedor,
                        'nombre': proveedor.nombre
                    }
                })
            
            lote_data['materias_primas_usadas'] = mp_data
            lotes_entregados_data.append(lote_data)

        report['lotes_entregados'] = lotes_entregados_data
        return report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró la línea de orden de venta con ID {id_orden_venta_producto}"}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}





def get_traceability_for_order(id_orden_venta):
    """
    Realiza la trazabilidad HACIA ATRÁS para TODOS los productos 
    de una Orden de Venta completa.

    Esta función actúa como un agregador, llamando a 
    get_traceability_backward() para cada línea de producto.

    Args:
        id_orden_venta (int): El ID de la OrdenVenta principal.

    Returns:
        dict: Un diccionario con el reporte de trazabilidad de todos
              los productos de la orden.
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
            'productos_trazados': [] # Aquí irá la lista
        }

        # 4. Iterar sobre CADA línea y llamar al servicio que ya teníamos
        for linea in lineas_de_la_orden:
            # Reutilizamos la función existente pasándole el ID de la LÍNEA (ej. 301)
            trace_report_linea = get_traceability_backward(linea.id_orden_venta_producto)
            
            # Limpiamos el reporte individual para no repetir datos
            if 'error' in trace_report_linea:
                full_report['productos_trazados'].append({
                    'id_orden_venta_producto': linea.id_orden_venta_producto,
                    'error': trace_report_linea['error']
                })
            else:
                # Agregamos solo las partes relevantes del sub-reporte
                full_report['productos_trazados'].append({
                    'producto_reclamado': trace_report_linea.get('producto_reclamado'),
                    'lotes_entregados': trace_report_linea.get('lotes_entregados')
                })

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
    





    