from datetime import date, timedelta
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from compras.models import (
    EstadoOrdenCompra, OrdenCompra, OrdenCompraProduccion, OrdenCompraMateriaPrima
)
from compras.serializers import (
    estadoOrdenCompraSerializer, ordenCompraProduccionSerializer, ordenCompraSerializer
)
from materias_primas.models import Proveedor


class ordenCompraViewSet(viewsets.ModelViewSet):
    queryset = OrdenCompra.objects.all()
    serializer_class = ordenCompraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["fecha_solicitud", "id_proveedor", "id_estado_orden_compra"]
    search_fields = ["id_proveedor__nombre"]

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
    serializer_class = ordenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_orden_produccion"]
    search_fields = ["id_orden_compra__numero_orden", "id_orden_produccion__codigo"]

class orden_compra_materia_primaViewSet(viewsets.ModelViewSet):
    queryset = OrdenCompraProduccion.objects.all()
    serializer_class = ordenCompraProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_orden_compra", "id_materia_prima"]
    search_fields = ["id_orden_compra__numero_orden", "id_materia_prima__nombre"]