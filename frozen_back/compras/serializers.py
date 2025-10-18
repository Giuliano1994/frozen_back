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