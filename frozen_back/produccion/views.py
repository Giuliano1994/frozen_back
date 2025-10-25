from django.shortcuts import render
from rest_framework import viewsets, filters, serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from produccion.services import gestionar_reservas_para_orden_produccion, descontar_stock_reservado, calcular_porcentaje_desperdicio_historico
from recetas.models import Receta, RecetaMateriaPrima
from productos.models import Producto
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad, estado_linea_produccion
from stock.models import EstadoLoteMateriaPrima, LoteMateriaPrima, LoteProduccion, EstadoLoteProduccion, LoteProduccionMateria, EstadoReservaMateria, ReservaMateriaPrima
from .serializers import (
    EstadoOrdenProduccionSerializer,
    LineaProduccionSerializer,
    OrdenProduccionSerializer,
    OrdenProduccionUpdateEstadoSerializer,
    NoConformidadSerializer,
    HistoricalOrdenProduccionSerializer
)
from .filters import OrdenProduccionFilter
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from ventas.services import revisar_ordenes_de_venta_pendientes
from rest_framework.decorators import api_view
# ------------------------------
# ViewSets básicos
# ------------------------------
class EstadoOrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = EstadoOrdenProduccion.objects.all()
    serializer_class = EstadoOrdenProduccionSerializer


class LineaProduccionViewSet(viewsets.ModelViewSet):
    queryset = LineaProduccion.objects.all()
    serializer_class = LineaProduccionSerializer

class EstadoLineaProduccionViewSet(viewsets.ModelViewSet):
    queryset = estado_linea_produccion.objects.all()
    serializer_class = EstadoOrdenProduccionSerializer


# ------------------------------
# ViewSet de OrdenProduccion
# ------------------------------


#V2
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
        """
        Crea una nueva orden de producción:
        - Gestiona reservas de materias primas
        - Determina el estado inicial según stock disponible
        - Crea automáticamente el lote de producción asociado
        """
        # Guardar la orden inicialmente
        estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")
        orden = serializer.save(id_estado_orden_produccion=estado_inicial)

        # Gestionar reservas de materias primas
        gestionar_reservas_para_orden_produccion(orden)

        # Crear el lote de producción automáticamente
        try:
            estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")
        except EstadoLoteProduccion.DoesNotExist:
            raise ValidationError({"error": 'No existe el estado "En espera" en LoteProduccion'})

        lote = LoteProduccion.objects.create(
            id_producto=orden.id_producto,
            id_estado_lote_produccion=estado_espera,
            cantidad=orden.cantidad,
            fecha_produccion=timezone.now().date(),
            fecha_vencimiento=timezone.now().date() + timedelta(days=orden.id_producto.dias_duracion)
        )

        orden.id_lote_produccion = lote
        orden.save()

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

        🔹 'Finalizada' → descuenta stock reservado, AJUSTA el lote por desperdicio y lo marca como disponible.
        🔹 'Cancelada' → no descuenta stock, cambia el lote a cancelado y libera el stock reservado.
        🔹 'Pendiente de inicio' → pone el lote en 'En espera'.
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

        # --- 🔹 CASO 1: ORDEN FINALIZADA ---
        if estado_descripcion == 'finalizada':
            try:
                # Descontar definitivamente el stock reservado (basado en la orden original, ej. 100 pizzas)
                descontar_stock_reservado(orden)
            except Exception as e:
                return Response(
                    {'error': f'Error al descontar stock reservado: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Marcar el lote de producción como "Disponible" Y AJUSTAR CANTIDAD
            if orden.id_lote_produccion:
                try:
                    estado_disponible = EstadoLoteProduccion.objects.get(descripcion__iexact="Disponible")
                    lote = orden.id_lote_produccion

                    # --- NUEVO: LÓGICA DE AJUSTE POR DESPERDICIO ---
                    
                    # 1. Calcular el total de desperdicio registrado para esta orden
                    total_desperdicio = NoConformidad.objects.filter(
                        id_orden_produccion=orden
                    ).aggregate(
                        total=Sum('cant_desperdiciada')
                    )['total'] or 0
                    
                    # 2. Obtener la cantidad planificada (ya sea de la orden o del lote)
                    #    Asumimos que lote.cantidad tiene el valor original (ej. 100)
                    cantidad_planificada = lote.cantidad 
                    
                    # 3. Calcular la cantidad final real y asegurarse de que no sea negativa
                    cantidad_final = max(0, cantidad_planificada - total_desperdicio)
                    
                    # 4. Actualizar el lote con la cantidad final (ej. 100 - 5 = 95)
                    lote.cantidad = cantidad_final
                    lote.id_estado_lote_produccion = estado_disponible
                    lote.save()
                    
                    # --- FIN NUEVO ---

                    # Revisar órdenes de venta pendientes
                    if lote.id_producto:
                        revisar_ordenes_de_venta_pendientes(lote.id_producto)

                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "Disponible" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        # --- 🔹 CASO 2: ORDEN CANCELADA ---
        elif estado_descripcion == 'cancelada':
            # (Esta lógica parece correcta y no necesita cambios para el desperdicio)
            if orden.id_lote_produccion:
                try:
                    estado_cancelado = EstadoLoteProduccion.objects.get(descripcion__iexact="Cancelado")
                    lote = orden.id_lote_produccion
                    lote.id_estado_lote_produccion = estado_cancelado
                    lote.save()
                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "Cancelado" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            # Liberar reservas y devolver stock reservado
            try:
                estado_activa = EstadoReservaMateria.objects.get(descripcion__iexact="Activa")
                estado_cancelada_reserva, _ = EstadoReservaMateria.objects.get_or_create(descripcion__iexact="Cancelada")

                reservas = ReservaMateriaPrima.objects.filter(
                    id_orden_produccion=orden,
                    id_estado_reserva_materia=estado_activa
                )

                # --- ERROR POTENCIAL CORREGIDO ---
                # No debes hacer 'lote_mp.cantidad_disponible += ...'
                # El @property 'cantidad_disponible' es calculado, no un campo de BBDD.
                # Simplemente cambiando el estado de la reserva a "Cancelada"
                # el @property 'cantidad_disponible' del lote se recalculará correctamente.
                for reserva in reservas:
                    reserva.id_estado_reserva_materia = estado_cancelada_reserva
                    reserva.save()
                # --- FIN CORRECCIÓN ---

            except EstadoReservaMateria.DoesNotExist:
                print("⚠️ No se encontró el estado 'Activa' en ReservaMateriaPrima")
            except Exception as e:
                return Response(
                    {'error': f'Error al liberar reservas: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # --- 🔹 CASO 3: ORDEN PENDIENTE DE INICIO ---
        elif estado_descripcion == 'pendiente de inicio':
             # (Esta lógica parece correcta)
            if orden.id_lote_produccion:
                try:
                    estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")
                    lote = orden.id_lote_produccion
                    lote.id_estado_lote_produccion = estado_espera
                    lote.save()
                except EstadoLoteProduccion.DoesNotExist:
                    return Response(
                        {'error': 'Estado de lote "En espera" no encontrado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
        elif estado_descripcion == 'en proceso':
            # Registrar la hora de inicio de la producción
            from django.utils import timezone
            orden.fecha_inicio = timezone.now()
            orden.save()

        # --- 🔹 OTROS ESTADOS ---
        else:
            print(f"Estado '{estado_descripcion}' no requiere acción especial.")

        # Serializar y devolver respuesta
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




class HistorialOrdenProduccionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para ver el historial de cambios de las Órdenes de Producción.
    """
    queryset = OrdenProduccion.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalOrdenProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_estado_orden_produccion', 'id_producto', 'id_supervisor', 'id_operario']
    search_fields = ['history_user__usuario', 'id_producto__nombre']



@api_view(['GET'])
def porcentaje_desperdicio_historico(request): # <-- Cambiar nombre de la función/vista
    """
    Devuelve el porcentaje de desperdicio histórico promedio para un producto,
    basado en las últimas 10 órdenes de producción finalizadas.

    Parámetro esperado en la URL (query param):
    - id_producto: El ID del producto.
    """
    id_producto_str = request.query_params.get('id_producto')

    # Validar parámetro
    if not id_producto_str:
        return Response(
            {"error": "Falta el parámetro 'id_producto'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        id_producto = int(id_producto_str)
    except (ValueError, TypeError):
        return Response(
            {"error": "El parámetro 'id_producto' debe ser un número entero."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validar que el producto exista
    if not Producto.objects.filter(pk=id_producto).exists():
         return Response({"error": f"El producto con ID {id_producto} no existe."}, status=status.HTTP_404_NOT_FOUND)

    # Llamar al servicio actualizado
    try:
        porcentaje = calcular_porcentaje_desperdicio_historico(id_producto)
        # Devolver solo el porcentaje en el JSON de respuesta
        return Response({"porcentaje_desperdicio": porcentaje}, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error al calcular porcentaje de desperdicio: {e}")
        return Response(
            {"error": "Ocurrió un error al calcular el porcentaje de desperdicio."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )