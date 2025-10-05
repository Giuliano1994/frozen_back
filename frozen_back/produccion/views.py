from django.shortcuts import render
from rest_framework import viewsets, filters, serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from stock.models import LoteProduccion, EstadoLoteProduccion
from .serializers import (
    EstadoOrdenProduccionSerializer,
    LineaProduccionSerializer,
    OrdenProduccionSerializer,
    OrdenProduccionUpdateEstadoSerializer,
    NoConformidadSerializer
)
from .filters import OrdenProduccionFilter
from django.utils import timezone
from datetime import timedelta

# ------------------------------
# ViewSets básicos
# ------------------------------
class EstadoOrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = EstadoOrdenProduccion.objects.all()
    serializer_class = EstadoOrdenProduccionSerializer


class LineaProduccionViewSet(viewsets.ModelViewSet):
    queryset = LineaProduccion.objects.all()
    serializer_class = LineaProduccionSerializer


# ------------------------------
# ViewSet de OrdenProduccion
# ------------------------------
class OrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = OrdenProduccion.objects.all().select_related(
        "id_estado_orden_produccion",
        "id_linea_produccion",
        "id_supervisor",
        "id_operario",
        "id_lote_produccion",
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrdenProduccionFilter
    search_fields = ['id_estado_orden_produccion__descripcion', 'id_linea_produccion__descripcion']
    ordering_fields = ['fecha_creacion', 'cantidad']
    ordering = ['-fecha_creacion']

    # Usar un serializer distinto para POST (acepta IDs)
    def get_serializer_class(self):
        if self.action == 'create':
            from .serializers import OrdenProduccionCreateSerializer  # lo definimos abajo
            return OrdenProduccionCreateSerializer
        return OrdenProduccionSerializer

    def perform_create(self, serializer):
        # Buscar el estado inicial "Pendiente de inicio"
        estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")

        # Guardar la orden con todos los datos de la request y el estado inicial
        orden = serializer.save(id_estado_orden_produccion=estado_inicial)

        # Buscar el estado "En espera" para el lote
        estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")

        # Crear lote asociado al producto
        lote = LoteProduccion.objects.create(
            id_producto=orden.id_producto,
            fecha_produccion=timezone.now().date(),
            fecha_vencimiento=timezone.now().date() + timedelta(days=orden.id_producto.dias_duracion),
            cantidad=orden.cantidad,
            id_estado_lote_produccion=estado_espera
        )

        # Asignar el lote recién creado a la orden
        orden.id_lote_produccion = lote
        orden.save()

    @action(detail=True, methods=['patch'])
    def actualizar_estado(self, request, pk=None):

        print("actualizar_estado")
        print(request.data)
        print(pk)
        print(self.get_object())
        """
        Endpoint personalizado para actualizar el estado de una orden de producción.
        Actualiza automáticamente el estado del lote asociado según las reglas de negocio.
        """
        try:
            orden = self.get_object()
        except OrdenProduccion.DoesNotExist:
            return Response(
                {'error': 'Orden de producción no encontrada'}, 
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OrdenProduccionUpdateEstadoSerializer(
            orden, 
            data=request.data, 
            partial=True
        )
        
        if serializer.is_valid():
            nuevo_estado = serializer.validated_data['id_estado_orden_produccion']
            estado_descripcion = nuevo_estado.descripcion
            
            print(f"Estado recibido: '{estado_descripcion}'")
            
            # Actualizar el estado de la orden
            orden.id_estado_orden_produccion = nuevo_estado
            orden.save()
            
            # Actualizar el estado del lote según las reglas de negocio
            if orden.id_lote_produccion:
                lote = orden.id_lote_produccion
                print(f"Lote encontrado: {lote}")
                
                if estado_descripcion.lower() == 'finalizada':
                    print("Finalizada - cambiando lote a Disponible")
                    # Si la orden está finalizada, el lote pasa a "Disponible"
                    try:
                        estado_disponible = EstadoLoteProduccion.objects.get(
                            descripcion__iexact="Disponible"
                        )
                        print(f"Estado disponible encontrado: {estado_disponible}")
                        lote.id_estado_lote_produccion = estado_disponible
                        lote.save()
                        print("Lote actualizado exitosamente")
                    except EstadoLoteProduccion.DoesNotExist:
                        print("Error: Estado 'Disponible' no encontrado")
                        return Response(
                            {'error': 'Estado de lote "Disponible" no encontrado'}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                        
                elif estado_descripcion.lower() == 'cancelado':
                    print("Cancelado - cambiando lote a Cancelado")
                    # Si la orden está cancelada, el lote pasa a "Cancelado"
                    try:
                        estado_cancelado = EstadoLoteProduccion.objects.get(
                            descripcion__iexact="Cancelado"
                        )
                        print(f"Estado cancelado encontrado: {estado_cancelado}")
                        lote.id_estado_lote_produccion = estado_cancelado
                        lote.save()
                        print("Lote cancelado exitosamente")
                    except EstadoLoteProduccion.DoesNotExist:
                        print("Error: Estado 'Cancelado' no encontrado")
                        return Response(
                            {'error': 'Estado de lote "Cancelado" no encontrado'}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                else:
                    print(f"No se requiere cambio de lote para estado: {estado_descripcion}")
            else:
                print("No hay lote asociado a esta orden")
            
            # Devolver la orden actualizada con toda la información
            response_serializer = OrdenProduccionSerializer(orden)
            return Response({
                'message': f'Estado de la orden actualizado a "{nuevo_estado.descripcion}"',
                'orden': response_serializer.data
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------------
# ViewSet de NoConformidad
# ------------------------------
class NoConformidadViewSet(viewsets.ModelViewSet):
    queryset = NoConformidad.objects.all().select_related("id_orden_produccion")
    serializer_class = NoConformidadSerializer
