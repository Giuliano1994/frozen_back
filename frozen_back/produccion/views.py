from django.shortcuts import render
from rest_framework import viewsets, filters, serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
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
        """
        Crea una nueva orden de producción.
        - Verifica si hay stock suficiente de materias primas según la receta del producto.
        - Si no hay suficiente stock, el estado inicial es 'En espera'.
        - Si hay suficiente stock, el estado inicial es 'Pendiente de inicio' y descuenta automáticamente el stock de los lotes.
        - Crea automáticamente el lote de producción asociado.
        """
        data = serializer.validated_data
        producto = data["id_producto"]
        cantidad_a_producir = data["cantidad"]

        # Buscar receta del producto
        try:
            receta = Receta.objects.get(id_producto=producto)
        except Receta.DoesNotExist:
            raise ValidationError({"error": f"No se encontró una receta para el producto {producto.nombre}"})

        # Obtener los ingredientes requeridos
        ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)

        # Verificar stock sumando los lotes "disponibles"
        stock_suficiente = True
        materias_faltantes = []

        try:
            estado_disponible = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")
        except EstadoLoteMateriaPrima.DoesNotExist:
            raise ValidationError({"error": 'No existe el estado "Disponible" en EstadoLoteMateriaPrima'})

        # Chequear stock
        for ingrediente in ingredientes:
            materia = ingrediente.id_materia_prima
            cantidad_necesaria = ingrediente.cantidad * cantidad_a_producir

            # Sumar los lotes disponibles de esa materia prima
            stock_total = (
                LoteMateriaPrima.objects.filter(
                    id_materia_prima=materia,
                    id_estado_lote_materia_prima=estado_disponible
                ).aggregate(total=Sum("cantidad"))["total"] or 0
            )

            if stock_total < cantidad_necesaria:
                stock_suficiente = False
                faltante = cantidad_necesaria - stock_total
                materias_faltantes.append({
                    "materia_prima": materia.nombre,
                    "faltante": faltante
                })

        # Determinar estado inicial según stock
        if stock_suficiente:
            estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")
        else:
            estado_inicial = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")

        # Guardar la orden con el estado inicial
        orden = serializer.save(id_estado_orden_produccion=estado_inicial)

        # Crear el lote de producción asociado
        estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")
        lote = LoteProduccion.objects.create(
            id_producto=orden.id_producto,
            fecha_produccion=timezone.now().date(),
            fecha_vencimiento=timezone.now().date() + timedelta(days=orden.id_producto.dias_duracion),
            cantidad=orden.cantidad,
            id_estado_lote_produccion=estado_espera
        )

        orden.id_lote_produccion = lote
        orden.save()

        # Si hay stock suficiente, descontar de los lotes (FIFO)
        if stock_suficiente:
            for ingrediente in ingredientes:
                materia = ingrediente.id_materia_prima
                cantidad_necesaria = ingrediente.cantidad * cantidad_a_producir

                lotes = (
                    LoteMateriaPrima.objects.filter(
                        id_materia_prima=materia,
                        id_estado_lote_materia_prima=estado_disponible
                    )
                    .order_by("fecha_vencimiento")  # FIFO: usa los más antiguos primero
                )

                for lote_mp in lotes:
                    if cantidad_necesaria <= 0:
                        break

                    if lote_mp.cantidad <= cantidad_necesaria:
                        cantidad_necesaria -= lote_mp.cantidad
                        lote_mp.cantidad = 0
                        # Opcional: cambiar estado del lote si se vació
                        estado_agotado, _ = EstadoLoteMateriaPrima.objects.get_or_create(descripcion__iexact="Agotado")
                        lote_mp.id_estado_lote_materia_prima = estado_agotado
                    else:
                        lote_mp.cantidad -= cantidad_necesaria
                        cantidad_necesaria = 0

                    lote_mp.save()

        # Si no hay stock suficiente, mostrar advertencia en consola ,Proximamente hay que agregar alerta al supervisor
        else:
            print(" Materias primas insuficientes para producir la totalidad del pedido:")
            for item in materias_faltantes:
                print(f"- {item['materia_prima']}: faltan {item['faltante']} unidades")



    @action(detail=True, methods=['patch'])
    def actualizar_estado(self, request, pk=None):

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
            
            # Actualizar el estado de la orden
            orden.id_estado_orden_produccion = nuevo_estado
            orden.save()
            
            # Actualizar el estado del lote según las reglas de negocio
            if orden.id_lote_produccion:
                lote = orden.id_lote_produccion
                
                if estado_descripcion.lower() == 'finalizada':
                    # Si la orden está finalizada, el lote pasa a "Disponible"
                    try:
                        estado_disponible = EstadoLoteProduccion.objects.get(
                            descripcion__iexact="Disponible"
                        )
                        lote.id_estado_lote_produccion = estado_disponible
                        lote.save()
                        if lote.id_producto:
                            print("Llamando a revisar_ordenes_de_venta_pendientes", lote.id_producto)
                            revisar_ordenes_de_venta_pendientes(lote.id_producto)
                    except EstadoLoteProduccion.DoesNotExist:
                        return Response(
                            {'error': 'Estado de lote "Disponible" no encontrado'}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                        
                elif estado_descripcion.lower() == 'cancelado':
                    # Si la orden está cancelada, el lote pasa a "Cancelado"
                    try:
                        estado_cancelado = EstadoLoteProduccion.objects.get(
                            descripcion__iexact="Cancelado"
                        )
                        lote.id_estado_lote_produccion = estado_cancelado
                        lote.save()
                    except EstadoLoteProduccion.DoesNotExist:
                        return Response(
                            {'error': 'Estado de lote "Cancelado" no encontrado'}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                elif estado_descripcion.lower() == 'Pendiente de inicio':
                    # Si la orden cambia a estado Pendiente de inicio, el lote pasa a "En espera""
                    try:
                        estado_espera = EstadoLoteProduccion.objects.get(descripcion__iexact="En espera")
                        lote.id_estado_lote_produccion = estado_espera
                        lote.save()
                    except EstadoLoteProduccion.DoesNotExist:
                        return Response(
                            {'error': 'Estado de lote "En espera" no encontrado'}, 
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