from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


# Asegúrate de que estas importaciones apunten a los servicios que corregimos
from .services import get_traceability_for_order, get_traceability_forward, get_traceability_backward_op 
from produccion.models import OrdenProduccion, OrdenProduccionPegging
from stock.models import ReservaMateriaPrima
from stock.models import ReservaStock, LoteProduccion, LoteProduccionMateria
from ventas.models import OrdenVenta, OrdenVentaProducto
from ventas.serializers import OrdenVentaSerializer

# Asumo que esta clase está en views.py de tu app de trazabilidad
class TrazabilidadViewSet(viewsets.ViewSet):
    """
    ViewSet para realizar consultas de trazabilidad usando los servicios corregidos.
    """

    # 1. Trazabilidad Hacia Atrás (Por Orden de Venta Completa) - Método Preferido
    # GET /api/trazabilidad/orden-venta/<id_ov>/backward/
    @action(detail=True, methods=['get'], url_path='backward')
    def trace_backward_by_order(self, request, pk=None):
        """
        Trazabilidad hacia atrás para una orden de venta COMPLETA (OV -> Lote PT -> Lote MP).
        Usa el PK (ID de OrdenVenta) en la URL.
        """
        if not pk:
            return Response(
                {"error": "El ID de la Orden de Venta (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            report = get_traceability_for_order(int(pk))
        except ValueError:
             return Response(
                {"error": "ID de Orden de Venta no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)

    # 2. Trazabilidad Hacia Adelante (Por Lote de Materia Prima)
    # GET /api/trazabilidad/mp-lote/<id_lote_mp>/forward/
    # NOTA: Este método debe ser un ViewSet separado o un @action(detail=False) 
    #       si no quieres usar el router principal, pero lo dejaremos como acción simple aquí.
    @action(detail=False, methods=['get'], url_path='hacia-adelante')
    def trace_forward_by_mp_lote(self, request):
        """
        Trazabilidad hacia adelante (Lote MP -> Lote PT -> Clientes).
        Requiere: ?id_lote_mp=<id_lote_materia_prima>
        """
        id_lote_mp = request.query_params.get('id_lote_mp')
        if not id_lote_mp:
            return Response(
                {"error": "Debe proporcionar el parámetro 'id_lote_mp' (ID de LoteMateriaPrima)"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            report = get_traceability_forward(int(id_lote_mp))
        except ValueError:
            return Response(
                {"error": "ID de Lote de Materia Prima no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
            
        return Response(report, status=status.HTTP_200_OK)
    
    # 3. Trazabilidad Interna (Por Orden de Producción)
    # GET /api/trazabilidad/op/<id_op>/audit/
    @action(detail=True, methods=['get'], url_path='audit')
    def trace_op_audit(self, request, pk=None):
        """
        Auditoría interna de una Orden de Producción (OP -> OT -> No Conformidades).
        Usa el PK (ID de OrdenProduccion) en la URL.
        """
        if not pk:
            return Response(
                {"error": "El ID de la Orden de Producción (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # Usamos la función auxiliar que creamos antes
            report = get_traceability_backward_op(int(pk)) 
        except ValueError:
             return Response(
                {"error": "ID de Orden de Producción no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)

    # 4. Obtener Órdenes de Venta (Endpoint para auditar el destino de un Lote PT)
    # GET /api/trazabilidad/lotes-pt/<id_lote_pt>/ordenes-venta/
    # NOTA: Este método necesita un ViewSet diferente (e.g., LoteProduccionViewSet) 
    #       para usar el router, pero lo dejamos aquí con un nombre más genérico.
    @action(detail=True, methods=['get'], url_path='ordenes-venta-asociadas')
    def obtener_ordenes_venta_por_lote(self, request, pk=None):
        """
        Obtiene todas las órdenes de venta que recibieron unidades de un Lote de Producción (pk).
        """
        if not pk:
            return Response(
                {"error": "El ID de Lote de Producción (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            # Reutilizamos tu lógica original, renombrada para mayor claridad
            lote_id = int(pk)
            # Paso 1: obtener reservas asociadas al lote
            reservas = ReservaStock.objects.filter(id_lote_produccion_id=lote_id)

            if not reservas.exists():
                return Response({"message": f"No se encontraron reservas para el lote {lote_id}."},
                                status=status.HTTP_404_NOT_FOUND)

            # Paso 2 y 3: Obtener IDs únicos de OrdenVenta a través de OrdenVentaProducto
            ids_orden_venta = OrdenVentaProducto.objects.filter(
                id_orden_venta_producto__in=reservas.values_list("id_orden_venta_producto_id", flat=True)
            ).values_list("id_orden_venta_id", flat=True).distinct()

            # Paso 4: traer las órdenes de venta
            ordenes = OrdenVenta.objects.filter(id_orden_venta__in=ids_orden_venta)

            serializer = OrdenVentaSerializer(ordenes, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValueError:
             return Response({"error": "ID de Lote de Producción no válido."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


@require_http_methods(["GET"])
def ordenes_por_lote_mp(request, id_lote):
    try:
        # 1. Obtener IDs desde la reserva
        reservas = ReservaMateriaPrima.objects.filter(id_lote_materia_prima=id_lote)
        
        if not reservas.exists():
            return JsonResponse({"exito": False, "mensaje": "Lote no encontrado o sin uso"}, status=404)

        ids_ordenes = reservas.values_list('id_orden_produccion', flat=True)

        # 2. Consultar las órdenes TRAYENDO los datos relacionados
        # select_related hace un JOIN SQL automático con las tablas Producto y Estado
        ordenes = OrdenProduccion.objects.filter(
            id_orden_produccion__in=ids_ordenes
        ).select_related('id_producto', 'id_estado_orden_produccion')

        # 3. Construir la lista manualmente para que quede bonita y clara
        lista_ordenes = []
        for orden in ordenes:
            print()

            lista_ordenes.append({
                "id_orden": orden.id_orden_produccion,
                "fecha_creacion": orden.fecha_creacion,
                "cantidad_a_producir": orden.cantidad,
                "fecha_planificada": orden.fecha_planificada,
                "lote_producto": orden.id_lote_produccion_id,
            
                # AQUÍ ACCEDEMOS A LOS DATOS DE LAS OTRAS TABLAS
                "producto": orden.id_producto.nombre,
                "estado": orden.id_estado_orden_produccion.descripcion
            })

        # 4. Respuesta Final
        data = {
            "exito": True,
            "lote_consultado": id_lote,
            "total_ordenes": len(lista_ordenes),
            "resultados": lista_ordenes
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)
    
@require_http_methods(["GET"])
def obtener_lotes_produccion_por_mp(request, id_lote_mp):
    try:
        # --- PASO 1: Buscar reservas (Igual que antes) ---
        reservas = ReservaMateriaPrima.objects.filter(id_lote_materia_prima=id_lote_mp)
        
        if not reservas.exists():
            return JsonResponse({"exito": False, "mensaje": "Lote MP no encontrado o sin uso"}, status=404)

        ids_ordenes = reservas.values_list('id_orden_produccion', flat=True)

        # --- PASO 2: Buscar IDs de Lotes Finales (Igual que antes) ---
        ordenes_con_lote = OrdenProduccion.objects.filter(
            id_orden_produccion__in=ids_ordenes,
            id_lote_produccion__isnull=False 
        )
        ids_lotes_finales = ordenes_con_lote.values_list('id_lote_produccion_id', flat=True)

        if not ids_lotes_finales:
            return JsonResponse({"exito": True, "mensaje": "Sin lotes finales aún", "lotes_produccion": []})

        # --- PASO 3: Consultar Lotes + PRODUCTO ---
        # AGREGAMOS .select_related('id_producto')
        lotes = LoteProduccion.objects.filter(
            id_lote_produccion__in=ids_lotes_finales
        ).select_related('id_producto')

        # --- PASO 4: Construir respuesta con el Nombre ---
        lista_resultados = []
        for lote in lotes:
            lista_resultados.append({
                "id_lote_produccion": lote.id_lote_produccion,
                "fecha_produccion": lote.fecha_produccion,
                "cantidad": lote.cantidad,
                
                # AQUÍ ESTÁ EL CAMBIO:
                # Accedemos al objeto relacionado para sacar el nombre
                "id_producto": lote.id_producto.id_producto, 
                "producto_nombre": lote.id_producto.nombre  
            })

        return JsonResponse({
            "exito": True,
            "lote_materia_prima_origen": id_lote_mp,
            "cantidad_encontrada": len(lista_resultados),
            "lotes_produccion": lista_resultados
        })

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)
    
def obtener_ordenes_venta_por_lote(request, id_lote):
    try:
        lista_ventas = []

        # ---------------------------------------------------------
        # RUTA A: BUSCAR EN RESERVA DE STOCK (Ya fabricado y guardado)
        # ---------------------------------------------------------
        reservas_stock = ReservaStock.objects.filter(
            id_lote_produccion=id_lote
        ).select_related(
            'id_orden_venta_producto',
            'id_orden_venta_producto__id_orden_venta',
            'id_orden_venta_producto__id_orden_venta__id_cliente'
        )

        for res in reservas_stock:
            ov = res.id_orden_venta_producto.id_orden_venta
            cliente = ov.id_cliente
            
            lista_ventas.append({
                "origen_asignacion": "STOCK (Deposito)",
                "id_orden_venta": ov.id_orden_venta,
                "cliente": cliente.nombre,
                "fecha_entrega": ov.fecha_entrega,
                "producto": res.id_orden_venta_producto.id_producto.nombre,
                "cantidad_asignada": res.cantidad_reservada
            })

        # ---------------------------------------------------------
        # RUTA B: BUSCAR EN PEGGING (Asignado durante la producción)
        # ---------------------------------------------------------
        # 1. Buscamos qué Orden de Producción fabricó este lote
        ordenes_prod = OrdenProduccion.objects.filter(id_lote_produccion=id_lote)
        ids_ops = ordenes_prod.values_list('id_orden_produccion', flat=True)

        if ids_ops:
            peggings = OrdenProduccionPegging.objects.filter(
                id_orden_produccion__in=ids_ops
            ).select_related(
                'id_orden_venta_producto',
                'id_orden_venta_producto__id_orden_venta',
                'id_orden_venta_producto__id_orden_venta__id_cliente'
            )

            for peg in peggings:
                ov = peg.id_orden_venta_producto.id_orden_venta
                cliente = ov.id_cliente

                lista_ventas.append({
                    "origen_asignacion": "PEGGING (Desde Producción)",
                    "id_orden_venta": ov.id_orden_venta,
                    "cliente": cliente.nombre,
                    "fecha_entrega": ov.fecha_entrega,
                    "producto": peg.id_orden_venta_producto.id_producto.nombre,
                    "cantidad_asignada": peg.cantidad_asignada
                })

        # ---------------------------------------------------------
        # RESPUESTA FINAL
        # ---------------------------------------------------------
        if not lista_ventas:
            return JsonResponse({
                "exito": True,
                "mensaje": "El lote existe pero está LIBRE (No asignado a ninguna venta ni en stock ni en producción).",
                "ordenes_venta": []
            })

        return JsonResponse({
            "exito": True,
            "lote_produccion_consultado": id_lote,
            "cantidad_ordenes_vinculadas": len(lista_ventas),
            "ordenes_venta": lista_ventas
        })

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)