from rest_framework import serializers
from .models import TipoProducto, Unidad, Producto


class TipoProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProducto
        fields = '__all__'


class UnidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unidad
        fields = '__all__'


class ProductoSerializer(serializers.ModelSerializer):
    tipo_producto = TipoProductoSerializer(source='id_tipo_producto', read_only=True)
    unidad = UnidadSerializer(source='id_unidad', read_only=True)

    class Meta:
        model = Producto
        fields = [
            'id_producto',
            'nombre',
            'descripcion',
            'precio',
            'id_tipo_producto',
            'id_unidad',
            'tipo_producto',
            'unidad',
            'umbral_minimo'
        ]


class ProductoLiteSerializer(serializers.ModelSerializer):
    unidad_medida = serializers.CharField(source="id_unidad.descripcion")

    class Meta:
        model = Producto
        fields = ["id_producto", "nombre", "descripcion", "unidad_medida", "umbral_minimo"]