from rest_framework import serializers
from .models import OrdenCompra, EstadoOrdenCompra, OrdenCompraMateriaPrima, OrdenCompraProduccion
from materias_primas.models import Proveedor

class estadoOrdenCompraSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoOrdenCompra
        fields = "__all__"


class OrdenCompraMateriaPrimaSerializer(serializers.ModelSerializer):
    materia_prima_nombre = serializers.CharField(source='id_materia_prima.nombre', read_only=True)

    class Meta:
        model = OrdenCompraMateriaPrima
        # Incluimos todos los campos manuales que queremos mostrar
        fields = ['id_materia_prima', 'cantidad', 'materia_prima_nombre']

class ordenCompraProduccionSerializer(serializers.ModelSerializer):
    orden_produccion_detalle = serializers.CharField(source='id_orden_produccion.detalle', read_only=True)

    class Meta:
        model = OrdenCompraProduccion
        fields = [
            "__all__"
        ]


class ordenCompraSerializer(serializers.ModelSerializer):
    materias_primas = OrdenCompraMateriaPrimaSerializer(
        source='ordencompramateriaprima_set',  # o el related_name si lo definiste
        many=True,
        read_only=True
    )

    class Meta:
        model = OrdenCompra
        fields = '__all__'  # incluye todos los campos de OrdenCompra + materias_primas



class OrdenCompraProduccionSerializer(serializers.ModelSerializer): # <--- Nombre corregido
    orden_produccion_detalle = serializers.CharField(source='id_orden_produccion.detalle', read_only=True)

    class Meta:
        model = OrdenCompraProduccion
        fields = [
            'id_orden_compra_produccion',
            'id_orden_compra',
            'id_orden_produccion',
            'orden_produccion_detalle'
        ]


class HistoricalOrdenCompraSerializer(serializers.ModelSerializer):
    # Campos legibles para el historial
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)
    estado_compra = serializers.CharField(source='id_estado_orden_compra.descripcion', read_only=True)
    proveedor_nombre = serializers.CharField(source='id_proveedor.nombre', read_only=True)

    class Meta:
        model = OrdenCompra.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre', 
            'id_estado_orden_compra', 'estado_compra', 
            'id_proveedor', 'proveedor_nombre', 
            'fecha_solicitud', 'fecha_entrega_estimada', 'fecha_entrega_real'
        ]