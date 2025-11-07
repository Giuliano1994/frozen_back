from django.shortcuts import get_object_or_404, render
from rest_framework import viewsets, filters, serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from produccion.services import gestionar_reservas_para_orden_produccion, descontar_stock_reservado, calcular_porcentaje_desperdicio_historico, verificar_y_actualizar_op_segun_ots
from recetas.models import Receta, RecetaMateriaPrima
from productos.models import Producto
from .models import EstadoOrdenProduccion, EstadoOrdenTrabajo, LineaProduccion, OrdenProduccion, NoConformidad, PausaOT, TipoNoConformidad, estado_linea_produccion, OrdenDeTrabajo
from stock.models import EstadoLoteMateriaPrima, LoteMateriaPrima, LoteProduccion, EstadoLoteProduccion, LoteProduccionMateria, EstadoReservaMateria, ReservaMateriaPrima
from .serializers import (
    EstadoOrdenProduccionSerializer,
    LineaProduccionSerializer,
    OrdenProduccionSerializer,
    OrdenProduccionUpdateEstadoSerializer,
    NoConformidadSerializer,
    HistoricalOrdenProduccionSerializer,
    OrdenDeTrabajoSerializer,
    TipoNoConformidadSerializer,
    NoConformidadCreateSerializer
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

class TipoNoConformidadViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar los Tipos de No Conformidad.
    """
    queryset = TipoNoConformidad.objects.all()
    serializer_class = TipoNoConformidadSerializer
# ------------------------------
# ViewSet de OrdenProduccion
# ------------------------------


class OrdenDeTrabajoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar las Órdenes de Trabajo (los fragmentos) con control de tiempo teórico.
    """
    queryset = OrdenDeTrabajo.objects.all().select_related(
        'id_orden_produccion', 
        'id_linea_produccion', 
        'id_estado_orden_trabajo'
    )
    serializer_class = OrdenDeTrabajoSerializer
    
    # --- UTILITY: Obtener Estado ---
    def _get_estado(self, descripcion):
        try:
            # Implementación REAL: Reemplaza con tu método real para obtener el estado
            return EstadoOrdenTrabajo.objects.get(descripcion__iexact=descripcion)
        except Exception as e:
            raise Exception(f"Estado de OT '{descripcion}' no encontrado.")
            
# --- Método perform_update (Mantenido) ---
    def perform_update(self, serializer):
        orden_trabajo = serializer.save()
        
        # 2. Llama a nuestro servicio de verificación
        if orden_trabajo.id_orden_produccion:
            verificar_y_actualizar_op_segun_ots(
                orden_trabajo.id_orden_produccion.id_orden_produccion
            )
            
    # =================================================================
    # 1. ACCIÓN INICIAR OT (Registra hora_inicio_real)
    # =================================================================
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def iniciar_ot(self, request, pk=None):
        """ Cambia el estado a 'En Progreso' y registra hora_inicio_real. """
        ot = get_object_or_404(OrdenDeTrabajo, pk=pk)
        
        if ot.id_estado_orden_trabajo.descripcion.lower() not in ['pendiente', 'planificada']:
            return Response(
                {'error': 'La OT debe estar en estado Pendiente o Planificada para iniciar.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        nuevo_estado = self._get_estado('En Progreso')
        
        ot.hora_inicio_real = timezone.now()
        ot.id_estado_orden_trabajo = nuevo_estado
        ot.save()
        
        return Response({'message': 'OT iniciada correctamente', 'estado': nuevo_estado.descripcion}, 
                        status=status.HTTP_200_OK)


    # =================================================================
    # 2. ACCIÓN PAUSAR OT (Registra pausa teórica)
    # =================================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def pausar_ot(self, request, pk=None):
        """ Crea una PausaOT activa y cambia el estado a 'En Pausa'. """
        ot = get_object_or_404(OrdenDeTrabajo, pk=pk)
        motivo = request.data.get('motivo')
        
        if ot.id_estado_orden_trabajo.descripcion.lower() != 'en progreso':
            return Response({'error': 'La OT debe estar en estado "En Progreso" para pausar.'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not motivo:
            return Response({'error': 'El motivo de la pausa es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)
        
        if ot.pausas.filter(activa=True).exists():
             return Response({'error': 'Ya existe una pausa activa. Debe reanudar primero.'}, status=status.HTTP_400_BAD_REQUEST)

        PausaOT.objects.create(
            id_orden_trabajo=ot,
            motivo=motivo,
            activa=True,
            duracion_minutos=0 
        )
        
        nuevo_estado = self._get_estado('En Pausa')
        ot.id_estado_orden_trabajo = nuevo_estado
        ot.save()

        return Response({'message': 'OT pausada correctamente'}, status=status.HTTP_200_OK)

    
    # =================================================================
    # 3. ACCIÓN REANUDAR OT (Define Duración Teórica y Finaliza Pausa)
    # =================================================================
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def reanudar_ot(self, request, pk=None):
        """ 
        Finaliza la PausaOT activa, asignando la duración teórica provista por el usuario.
        """
        ot = get_object_or_404(OrdenDeTrabajo, pk=pk)
        
        duracion_pausa_teorica = request.data.get('duracion_minutos', 0)
        
        if ot.id_estado_orden_trabajo.descripcion.lower() != 'en pausa':
            return Response({'error': 'La OT debe estar en estado "En Pausa" para reanudar.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            duracion = int(duracion_pausa_teorica)
            if duracion < 0: raise ValueError
        except ValueError:
             return Response({'error': 'La duración de la pausa debe ser un número entero positivo.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ultima_pausa = ot.pausas.get(activa=True)
            
            ultima_pausa.duracion_minutos = duracion 
            ultima_pausa.activa = False
            ultima_pausa.save()
            
        except PausaOT.DoesNotExist:
            return Response({'error': 'No hay pausas activas para reanudar.'}, status=status.HTTP_400_BAD_REQUEST)

        nuevo_estado = self._get_estado('En Progreso')
        ot.id_estado_orden_trabajo = nuevo_estado
        ot.save()

        return Response({
            'message': f'OT reanudada. Pausa registrada con duración de {duracion} minutos.',
            'estado': nuevo_estado.descripcion
        }, status=status.HTTP_200_OK)


    # =================================================================
    # 4. ACCIÓN FINALIZAR OT (Calcula duración planificada en el momento)
    # =================================================================
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def finalizar_ot(self, request, pk=None):
        """ 
        Cambia el estado a 'Completada', calcula hora_fin_real (tiempo teórico + pausas)
        y establece la cantidad_producida (Programada - Desperdicio).
        """
        ot = get_object_or_404(OrdenDeTrabajo, pk=pk)
        
        # Validaciones (Mantenidas)
        if ot.id_estado_orden_trabajo.descripcion.lower() != 'en progreso':
            return Response({'error': 'La OT debe estar en estado "En Progreso" para finalizar.'}, status=status.HTTP_400_BAD_REQUEST)
        if not ot.hora_inicio_real:
            return Response({'error': 'La OT no tiene hora de inicio real registrada.'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Validar Pausas Activas (Mantenido)
        if ot.pausas.filter(activa=True).exists():
            return Response({'error': 'No se puede finalizar. Hay una pausa activa que debe ser reanudada.'}, status=status.HTTP_400_BAD_REQUEST)

        # 2. CALCULAR LA DURACIÓN PLANIFICADA EN MINUTOS (Mantenido)
        if not ot.hora_fin_programada or not ot.hora_inicio_programada:
            return Response({'error': 'La OT no tiene un horario planificado completo (inicio/fin).'}, status=status.HTTP_400_BAD_REQUEST)
            
        duracion_planificada_delta = ot.hora_fin_programada - ot.hora_inicio_programada
        duracion_planificada_minutos = duracion_planificada_delta.total_seconds() / 60
        
        # 3. Sumar el tiempo total de pausas (Mantenido)
        tiempo_pausa_total_minutos = ot.pausas.filter(activa=False).aggregate(
            total_pausa=Sum('duracion_minutos')
        )['total_pausa'] or 0
        
        # 4. Calcular hora_fin_real (Mantenido)
        tiempo_operacion_total = duracion_planificada_minutos + tiempo_pausa_total_minutos
        ot.hora_fin_real = ot.hora_inicio_real + timedelta(minutes=tiempo_operacion_total)


        # =================================================================
        # ⚡ NUEVA LÓGICA: CALCULAR CANTIDAD PRODUCIDA REAL
        # =================================================================

        # 4.1. Sumar el desperdicio total registrado en las No Conformidades de esta OT
        total_desperdicio_query = ot.noconformidad_set.aggregate(
            total_desperdicio=Sum('cant_desperdiciada')
        )
        # Coalesce: Si no hay desperdicio (la suma es None), se considera 0
        total_desperdicio = total_desperdicio_query.get('total_desperdicio') or 0

        # 4.2. Cantidad Producida = Cantidad Programada - Total Desperdicio
        cantidad_producida_real = ot.cantidad_programada - total_desperdicio
        
        # Aseguramos que la cantidad no sea negativa
        ot.cantidad_producida = max(0, cantidad_producida_real)
        
        # =================================================================

        # 5. Actualizar estado y guardar (Mantenido)
        nuevo_estado = self._get_estado('Completada')
        ot.id_estado_orden_trabajo = nuevo_estado
        ot.save() # Se guardan todos los cambios, incluyendo hora_fin_real y cantidad_producida
        
        # 6. Llama al servicio de verificación de OP padre (Mantenido)
        if ot.id_orden_produccion:
            verificar_y_actualizar_op_segun_ots(ot.id_orden_produccion.id_orden_produccion)

        return Response({
            'message': 'OT finalizada correctamente',
            'cantidad_producida': ot.cantidad_producida,
            'total_desperdicio_registrado': total_desperdicio
        }, status=status.HTTP_200_OK)
    # =================================================================
    # 5. ACCIÓN REGISTRAR NO CONFORMIDAD (NUEVO)
    # =================================================================
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def registrar_no_conformidad(self, request, pk=None):
        """ 
        Registra una No Conformidad con su tipo asociado y cantidad desperdiciada.
        Solo permitido si el estado es 'En Progreso'.
        """
        ot = get_object_or_404(OrdenDeTrabajo, pk=pk)
        
        # 1. Validación de Estado
        if ot.id_estado_orden_trabajo.descripcion.lower() != 'en progreso':
            return Response(
                {'error': 'La No Conformidad solo puede registrarse cuando la OT está en estado "En Progreso".'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 2. Serialización y Validación de Datos (Usando el serializer de creación)
        # Importante: Asume que tienes el NoConformidadCreateSerializer definido e importado
        serializer = NoConformidadCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # 3. Guardar la No Conformidad
        # Asignamos la OT actual antes de guardar
        serializer.save(id_orden_trabajo=ot)
        
        # 4. Respuesta
        return Response({
            'message': 'No Conformidad registrada correctamente para esta Orden de Trabajo.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


#V2
class OrdenProduccionViewSet(viewsets.ModelViewSet):
    queryset = OrdenProduccion.objects.all().select_related(
        "id_estado_orden_produccion",
    #    "id_linea_produccion",
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

        # --- 1. VALIDACIÓN DE LÓGICA DE NEGOCIO ---
        if estado_descripcion == 'finalizada':
            if orden.id_estado_orden_produccion.descripcion.lower() != 'finalizada':
                return Response(
                    {'error': 'No se puede forzar el estado "Finalizada" manualmente. '
                              'Este estado se aplica automáticamente cuando todas '
                              'las Órdenes de Trabajo asociadas se completan.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Actualizar el estado de la orden (SOLO si no es 'finalizada' o ya lo era)
        orden.id_estado_orden_produccion = nuevo_estado
        orden.save()

        if estado_descripcion == 'finalizada':
            pass # No hacer nada aquí, solo permitir la llamada si ya estaba finalizada

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
            try:
                # Obtener los estados relevantes
                estado_ot_cancelada = EstadoOrdenTrabajo.objects.get(descripcion__iexact='Cancelada')
                estados_finales_ot = EstadoOrdenTrabajo.objects.filter(
                    Q(descripcion__iexact='Completada') | Q(descripcion__iexact='Cancelada')
                )
                
                # Buscar OTs hijas que NO estén ya en un estado final
                ots_a_cancelar = orden.ordenes_de_trabajo.exclude(
                    id_estado_orden_trabajo__in=estados_finales_ot
                )
                
                # Cancelarlas en lote
                count = ots_a_cancelar.count()
                if count > 0:
                    ots_a_cancelar.update(id_estado_orden_trabajo=estado_ot_cancelada)
                    print(f"Canceladas {count} Órdenes de Trabajo hijas de la OP {orden.id_orden_produccion}.")
            
            except EstadoOrdenTrabajo.DoesNotExist:
                print(f"Advertencia: No se pudo encontrar el estado 'Cancelada' para OrdenDeTrabajo.")

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


    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        Borra órdenes de producción dentro de un rango de IDs pasados como query params: ?inicio=100&fin=50
        """
        inicio = request.query_params.get('inicio')
        fin = request.query_params.get('fin')

        if not inicio or not fin:
            return Response({"detail": "Se requieren parámetros 'inicio' y 'fin'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            inicio = int(inicio)
            fin = int(fin)
        except ValueError:
            return Response({"detail": "Los parámetros deben ser enteros"}, status=status.HTTP_400_BAD_REQUEST)

        id_min = min(inicio, fin)
        id_max = max(inicio, fin)

        ordenes = OrdenProduccion.objects.filter(id_orden_produccion__gte=id_min,
                                                 id_orden_produccion__lte=id_max)
        count = ordenes.count()
        ordenes.delete()  # Esto borrará automáticamente los NoConformidad por on_delete=CASCADE
        return Response({"detail": f"{count} órdenes de producción borradas"}, status=status.HTTP_204_NO_CONTENT)
    
    
# ------------------------------
# ViewSet de NoConformidad
# ------------------------------
class NoConformidadViewSet(viewsets.ModelViewSet):
    queryset = NoConformidad.objects.all().select_related("id_orden_produccion","id_tipo_no_conformidad")
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