from django.shortcuts import render
from rest_framework import viewsets, filters, serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from produccion.services import gestionar_reservas_para_orden_produccion, descontar_stock_reservado
from recetas.models import Receta, RecetaMateriaPrima
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from stock.models import EstadoLoteMateriaPrima, LoteMateriaPrima, LoteProduccion, EstadoLoteProduccion, LoteProduccionMateria
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
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from ventas.services import revisar_ordenes_de_venta_pendientes
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
        estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="En Espera")
        orden = serializer.save(id_estado_orden_produccion=estado_inicial)
        gestionar_reservas_para_orden_produccion(orden)
        return orden

    @action(detail=True, methods=['post'])
    def iniciar_produccion(self, request, pk=None):
        orden = self.get_object()
        descontar_stock_reservado(orden)
        return Response({"mensaje": "Producción iniciada y stock descontado."})



    @action(detail=True, methods=['patch'])
    def actualizar_estado(self, request, pk=None):
        """
        Actualiza el estado de la orden de producción.
        🔹 Si pasa a 'Finalizada' → descuenta stock reservado y marca el lote como disponible.
        🔹 Si pasa a 'Cancelada' → no descuenta stock, solo cambia el estado del lote.
        🔹 Si pasa a 'Pendiente de inicio' → pone el lote en 'En espera'.
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

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        nuevo_estado = serializer.validated_data['id_estado_orden_produccion']
        estado_descripcion = nuevo_estado.descripcion.lower()

        # Actualizar el estado de la orden
        orden.id_estado_orden_produccion = nuevo_estado
        orden.save()

        # --- 🔹 Caso 1: Orden FINALIZADA ---
        if estado_descripcion == 'finalizada':
            # Consumir la materia prima
            try:
                descontar_stock_reservado(orden)
            except Exception as e:
                return Response(
                    {'error': f'Error al descontar stock: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Marcar el lote como disponible
            if orden.id_lote_produccion:
                try:
                    estado_disponible = EstadoLoteProduccion.objects.get(
                        descripcion__iexact="Disponible"
                    )
                    lote = orden.id_lote_produccion
                    lote.id_estado_lote_produccion = estado_disponible
                    lote.save()

                    # Revisar órdenes de venta pendientes del producto fabricado
                    if lote.id_producto:
                        revisar_ordenes_de_venta_pendientes(lote.id_producto)

                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "Disponible" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        # --- 🔹 Caso 2: Orden CANCELADA ---
        elif estado_descripcion.lower() == 'cancelada':
    # NO se descuenta stock
    # Actualizar el lote asociado
            if orden.id_lote_produccion:
                try:
                    estado_cancelado = EstadoLoteProduccion.objects.get(
                        descripcion__iexact="Cancelado"
                    )
                    lote = orden.id_lote_produccion
                    lote.id_estado_lote_produccion = estado_cancelado
                    lote.save()
                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "Cancelado" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            # Liberar reservas de materia prima
            try:
                estado_activa = EstadoReservaMateria.objects.get(descripcion__iexact="Activa")
                estado_cancelada_reserva, _ = EstadoReservaMateria.objects.get_or_create(descripcion__iexact="Cancelada")
                reservas = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=orden,
                    id_estado_reserva_materia=estado_activa
                )
                reservas.update(id_estado_reserva_materia=estado_cancelada_reserva)
            except EstadoReservaMateria.DoesNotExist:
                print("No se encontró el estado 'Activa' en ReservaMateriaPrima")


        # --- 🔹 Caso 3: Orden Pendiente de inicio ---
        elif estado_descripcion == 'pendiente de inicio':
            if orden.id_lote_produccion:
                try:
                    estado_espera = EstadoLoteProduccion.objects.get(
                        descripcion__iexact="En espera"
                    )
                    lote = orden.id_lote_produccion
                    lote.id_estado_lote_produccion = estado_espera
                    lote.save()
                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "En espera" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        # --- 🔹 Otros estados ---
        else:
            print(f"Estado '{estado_descripcion}' no requiere acción especial.")

        # Devolver la orden actualizada
        response_serializer = OrdenProduccionSerializer(orden)
        return Response({
            'message': f'Estado de la orden actualizado a \"{nuevo_estado.descripcion}\"',
            'orden': response_serializer.data
        }, status=status.HTTP_200_OK)



# ------------------------------
# ViewSet de NoConformidad
# ------------------------------
class NoConformidadViewSet(viewsets.ModelViewSet):
    queryset = NoConformidad.objects.all().select_related("id_orden_produccion")
    serializer_class = NoConformidadSerializer