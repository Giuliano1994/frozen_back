from datetime import date, timedelta
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction
from compras.models import (
    EstadoOrdenCompra, OrdenCompra, OrdenCompraProduccion, OrdenCompraMateriaPrima
)
from compras.serializers import (
    estadoOrdenCompraSerializer, OrdenCompraProduccionSerializer, ordenCompraSerializer, OrdenCompraMateriaPrimaSerializer
)
from produccion.services import procesar_ordenes_en_espera
from materias_primas.models import Proveedor
from materias_primas.models import MateriaPrima
from .services import crear_lotes_materia_prima


class ordenCompraViewSet(viewsets.ModelViewSet):
    queryset = OrdenCompra.objects.all()
    serializer_class = ordenCompraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["fecha_solicitud", "id_proveedor", "id_estado_orden_compra"]
    search_fields = ["id_proveedor__nombre"]

    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def actualizar_estado(self, request, pk=None):
        """
        Actualiza el estado de una orden de compra.
        
        Si el nuevo estado es 'Recibido':
        - Requiere una lista de materias_recibidas en el body con la estructura:
          [{"id_materia_prima": 1, "cantidad": 100}, ...]
        - Crea los lotes de materia prima correspondientes
        - Actualiza la fecha_entrega_real
        
        Si el estado es 'Cancelado':
        - Simplemente actualiza el estado de la orden
        """
        try:
            orden = self.get_object()
            nuevo_estado_id = request.data.get('id_estado_orden_compra')
            
            if not nuevo_estado_id:
                return Response(
                    {"error": "Debe especificar id_estado_orden_compra"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            nuevo_estado = EstadoOrdenCompra.objects.get(id_estado_orden_compra=nuevo_estado_id)
            descripcion_estado = nuevo_estado.descripcion.lower()
            
            # Actualizar el estado de la orden
            orden.id_estado_orden_compra = nuevo_estado
            
            if descripcion_estado == 'recibido':
                materias_recibidas = request.data.get('materias_recibidas')
                
                if not materias_recibidas:
                    return Response(
                        {"error": "Debe especificar las materias_recibidas"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Crear los lotes de materia prima
                lotes_creados = crear_lotes_materia_prima(orden, materias_recibidas)
                
                # Actualizar fecha de entrega real
                orden.fecha_entrega_real = timezone.now().date()

                for mp in materias_recibidas:
                    mp_id = mp.get("id_materia_prima")
                    if not mp_id:
                        # ignorar entradas inválidas
                        continue
                    materia = MateriaPrima.objects.filter(id_materia_prima=mp_id).first()
                    if materia:
                        try:
                            procesar_ordenes_en_espera(materia)
                        except Exception as e:
                            # registrar y seguir con las demás
                            print(f"Error procesando órdenes en espera para materia {mp_id}: {e}")
                    else:
                        print(f"Advertencia: MateriaPrima id={mp_id} no encontrada al procesar ordenes en espera.")
            
            orden.save()
            
            return Response({
                "mensaje": f"Estado actualizado a {nuevo_estado.descripcion}",
                "lotes_creados": len(lotes_creados) if descripcion_estado == 'recibido' else 0
            })
            
        except EstadoOrdenCompra.DoesNotExist:
            return Response(
                {"error": "El estado especificado no existe"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"Error al actualizar el estado: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Crea una orden de compra con sus materias primas asociadas.
        - La fecha de solicitud es la fecha actual.
        - Calcula la fecha estimada según el lead_time_day del proveedor.
        - Asigna estado 'En proceso' automáticamente.
        """
        try:
            data = request.data

            # Buscar el estado "En proceso"
            estado = EstadoOrdenCompra.objects.filter(descripcion__iexact="En proceso").first()
            if not estado:
                return Response(
                    {"error": "No existe un estado de orden de compra con descripción 'En proceso'."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Buscar el proveedor
            proveedor_id = data.get("id_proveedor")
            proveedor = Proveedor.objects.filter(id_proveedor=proveedor_id).first()
            if not proveedor:
                return Response(
                    {"error": "El proveedor especificado no existe."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Fecha actual como fecha de solicitud
            fecha_solicitud = date.today()

            # Calcular la fecha estimada usando el lead_time_day del proveedor
            fecha_entrega_estimada = fecha_solicitud + timedelta(days=proveedor.lead_time_days)

            # Crear la orden de compra
            orden = OrdenCompra.objects.create(
                id_estado_orden_compra=estado,
                id_proveedor=proveedor,
                fecha_solicitud=fecha_solicitud,
                fecha_entrega_estimada=fecha_entrega_estimada
            )

            # Crear las materias primas asociadas
            materias_primas = data.get("materias_primas", [])
            for mp in materias_primas:
                OrdenCompraMateriaPrima.objects.create(
                    id_orden_compra=orden,
                    id_materia_prima_id=mp.get("id_materia_prima"),
                    cantidad=mp.get("cantidad")
                )

            # Serializar y devolver la orden creada
            serializer = self.get_serializer(orden)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class estadoOrdenCompraViewSet(viewsets.ModelViewSet):
    queryset = EstadoOrdenCompra.objects.all()
    serializer_class = estadoOrdenCompraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["descripcion"]
    search_fields = ["descripcion"]

class orden_compra_produccionViewSet(viewsets.ModelViewSet):
    queryset = OrdenCompraProduccion.objects.all()
    serializer_class = OrdenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_orden_produccion"]
    search_fields = ["id_orden_compra__numero_orden", "id_orden_produccion__codigo"]

"""
class orden_compra_materia_primaViewSet(viewsets.ModelViewSet):
    queryset = OrdenCompraProduccion.objects.all()
    serializer_class = ordenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_materia_prima"]
    search_fields = ["id_orden_compra__numero_orden", "id_materia_prima__nombre"]
"""


# --- 2. CORREGIR ESTE VIEWSET COMPLETAMENTE ---
class orden_compra_materia_primaViewSet(viewsets.ModelViewSet):
    # Apuntar al modelo correcto
    queryset = OrdenCompraMateriaPrima.objects.all() 
    # Apuntar al serializador correcto (con mayúsculas)
    serializer_class = OrdenCompraMateriaPrimaSerializer 
    
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    
    # Estos campos AHORA SÍ son correctos porque el queryset apunta a OrdenCompraMateriaPrima
    filterset_fields = ["id_orden_compra", "id_materia_prima"] 
    search_fields = ["id_orden_compra__numero_orden", "id_materia_prima__nombre"]