from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
# Asegúrate de que estas importaciones apunten a los servicios que corregimos
from .services import get_traceability_for_order, get_traceability_forward, get_traceability_backward_op 

from stock.models import ReservaStock, LoteProduccion
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