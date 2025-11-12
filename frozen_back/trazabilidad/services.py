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





def get_traceability_for_order(id_orden_venta):
    """
    Realiza la trazabilidad HACIA ATRÁS (Venta -> PT Lote -> MP Lote -> Proveedor).
    
    1. Venta (OrdenVenta)
    2. PT Lote (LoteProduccion): Usando ReservaStock.
    3. OP (OrdenProduccion): Usando LoteProduccion.
    4. MP Lote (LoteMateriaPrima): Usando LoteProduccionMateria.
    5. Proveedor (MateriaPrima.id_proveedor).
    """
    try:
        orden = OrdenVenta.objects.select_related('id_cliente').get(pk=id_orden_venta)
        full_report = {
            'id_orden_venta': orden.id_orden_venta,
            'cliente': {'id_cliente': orden.id_cliente.id_cliente, 'nombre': orden.id_cliente.nombre},
            'productos_trazados': []
        }

        # Iterar sobre las líneas de la orden de venta
        lineas_de_la_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden)

        for linea in lineas_de_la_orden:
            producto_report = {
                'producto': linea.id_producto.nombre if linea.id_producto else 'Desconocido',
                'cantidad_vendida': linea.cantidad,
                'lotes_entregados': [],
                'total_trazado': 0
            }
            
            # Buscar el Lote de Producción (PT) que satisfizo esta línea de venta a través de la ReservaStock
            reservas_entregadas = ReservaStock.objects.filter(
                id_orden_venta_producto=linea,
                # CRÍTICO: Asumo que 'Activa' representa stock usado o 'Entregado'. 
                # Si usas otro estado para el consumo final, cámbialo aquí.
                id_estado_reserva__descripcion='Activa' 
            ).select_related(
                'id_lote_produccion', 
                'id_lote_produccion__id_producto'
            )

            for reserva in reservas_entregadas:
                lote_prod = reserva.id_lote_produccion
                
                # Obtener la Orden de Producción asociada al Lote de Producción
                op_asociada = OrdenProduccion.objects.filter(id_lote_produccion=lote_prod).first()
                op_id = op_asociada.id_orden_produccion if op_asociada else 'N/A'

                lote_data = {
                    'id_lote_produccion': lote_prod.id_lote_produccion,
                    'cantidad_reservada': reserva.cantidad_reservada,
                    'fecha_produccion': lote_prod.fecha_produccion.isoformat(),
                    'fecha_vencimiento': lote_prod.fecha_vencimiento.isoformat(),
                    'orden_produccion_id': op_id,
                    'materias_primas_usadas': get_mp_trace_for_lote(lote_prod.id_lote_produccion)
                }
                producto_report['lotes_entregados'].append(lote_data)
                producto_report['total_trazado'] += reserva.cantidad_reservada

            full_report['productos_trazados'].append(producto_report)
            
        return full_report

    except OrdenVenta.DoesNotExist:
        return {"error": f"No se encontró la orden de venta con ID {id_orden_venta}"}
    except Exception as e:
        return {"error": f"Error inesperado en trazabilidad hacia atrás: {str(e)}"}


def get_mp_trace_for_lote(id_lote_produccion):
    """
    Función auxiliar para obtener la trazabilidad de MP (Lote -> Materia Prima -> Proveedor)
    para un Lote de Producción específico.
    """
    mp_data = []
    try:
        # Obtenemos los vínculos entre Lote de PT y Lote de MP
        materias_usadas = LoteProduccionMateria.objects.filter(
            id_lote_produccion=id_lote_produccion
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
    except Exception as e:
        mp_data.append({'error': f"Error al buscar MP para Lote PT {id_lote_produccion}: {str(e)}"})
        
    return mp_data

def get_traceability_forward(id_lote_materia_prima):
    """
    Realiza la trazabilidad HACIA ADELANTE (MP Lote -> PT Lote -> Cliente).
    
    1. Lote MP (LoteMateriaPrima).
    2. PT Lote (LoteProduccion): Usando LoteProduccionMateria.
    3. Clientes (OrdenVenta): Usando ReservaStock.
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
            'fecha_vencimiento': lote_mp.fecha_vencimiento.isoformat(),
        }
        report['proveedor'] = {
            'id_proveedor': lote_mp.id_materia_prima.id_proveedor.id_proveedor,
            'nombre': lote_mp.id_materia_prima.id_proveedor.nombre,
        }

        # 2. LOTES DE PRODUCCIÓN AFECTADOS
        lotes_prod_links = LoteProduccionMateria.objects.filter(
            id_lote_materia_prima=lote_mp
        ).select_related(
            'id_lote_produccion',
            'id_lote_produccion__id_producto'
        )

        lotes_afectados_data = []
        for link in lotes_prod_links:
            lote_prod = link.id_lote_produccion
            lote_data = {
                'id_lote_produccion': lote_prod.id_lote_produccion,
                'producto_nombre': lote_prod.id_producto.nombre,
                'fecha_produccion': lote_prod.fecha_produccion.isoformat(),
                'fecha_vencimiento': lote_prod.fecha_vencimiento.isoformat(),
                'cantidad_usada_en_lote': link.cantidad_usada,
                'clientes_afectados': []
            }

            # 3. CLIENTES AFECTADOS
            # Buscamos todas las reservas activas (o el estado que representa la entrega final)
            reservas = ReservaStock.objects.filter(
                id_lote_produccion=lote_prod,
                # CRÍTICO: Asumo que 'Activa' o 'Entregada' representan la entrega al cliente.
                id_estado_reserva__descripcion__in=['Activa', 'Entregada'] 
            ).select_related(
                'id_orden_venta_producto__id_orden_venta',
                'id_orden_venta_producto__id_orden_venta__id_cliente'
            )

            clientes_data = []
            for reserva in reservas:
                orden = reserva.id_orden_venta_producto.id_orden_venta
                cliente = orden.id_cliente
                
                clientes_data.append({
                    'id_cliente': cliente.id_cliente,
                    'nombre_cliente': cliente.nombre,
                    'id_orden_venta': orden.id_orden_venta,
                    'fecha_orden': orden.fecha.isoformat(),
                    'cantidad_entregada_por_lote': reserva.cantidad_reservada
                })
            
            lote_data['clientes_afectados'] = clientes_data
            lotes_afectados_data.append(lote_data)

        report['lotes_produccion_afectados'] = lotes_afectados_data
        return report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró el lote de materia prima con ID {id_lote_materia_prima}"}
    except Exception as e:
        return {"error": f"Error inesperado en trazabilidad hacia adelante: {str(e)}"}
    

def get_traceability_backward_op(id_orden_produccion):
    
    """
    Rastrea hacia atrás desde una Orden de Producción (OP) específica,
    incluyendo las Órdenes de Trabajo (OT) y las No Conformidades.
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

        op_report['orden_produccion'] = {
            'id_orden_produccion': orden_produccion.id_orden_produccion,
            'fecha_creacion': orden_produccion.fecha_creacion.isoformat(),
            'cantidad_planificada': orden_produccion.cantidad,
            'lote_asociado': lote.id_lote_produccion if lote else 'N/A',
            'operarios': [
                {'rol': 'Supervisor', 'nombre': orden_produccion.id_supervisor.nombre if orden_produccion.id_supervisor else 'N/A'},
                {'rol': 'Operario', 'nombre': orden_produccion.id_operario.nombre if orden_produccion.id_operario else 'N/A'},
            ],
            'ordenes_de_trabajo': [] 
        }

        # 2. ORDENES DE TRABAJO (OT) y No Conformidades
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
                total_desperdiciado = sum(nc.cant_desperdiciada for nc in ot.no_conformidades.all())
                ot_data = {
                    'id_orden_trabajo': ot.id_orden_trabajo,
                    'linea_produccion': ot.id_linea_produccion.descripcion,
                    'estado': ot.id_estado_orden_trabajo.descripcion if ot.id_estado_orden_trabajo else 'N/A',
                    'cantidad_producida_neta': ot.cantidad_producida,
                    'cantidad_desperdiciada_total': total_desperdiciado,
                    'inicio_real': ot.hora_inicio_real.isoformat() if ot.hora_inicio_real else 'N/A',
                    'fin_real': ot.hora_fin_real.isoformat() if ot.hora_fin_real else 'N/A',
                    'no_conformidades_detalles': [
                        {
                            'tipo': nc.id_tipo_no_conformidad.nombre,
                            'cantidad': nc.cant_desperdiciada
                        } 
                        for nc in ot.no_conformidades.all()
                    ]
                }
                op_report['orden_produccion']['ordenes_de_trabajo'].append(ot_data)
        else:
            op_report['orden_produccion']['ordenes_de_trabajo'] = [{'info': 'No se encontraron Órdenes de Trabajo asociadas a esta OP.'}]

        # 3. MATERIAS PRIMAS (tomadas del Lote de PT asociado)
        if lote:
            op_report['materias_primas_usadas'] = get_mp_trace_for_lote(lote.id_lote_produccion)
        else:
            op_report['materias_primas_usadas'] = []
        
        return op_report

    except ObjectDoesNotExist:
        return {"error": f"No se encontró la Orden de Producción con ID {id_orden_produccion}"}
    except Exception as e:
        return {"error": f"Error inesperado al rastrear la OP {id_orden_produccion}: {str(e)}"}