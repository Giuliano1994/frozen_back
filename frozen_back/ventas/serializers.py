from rest_framework import serializers
from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto
from productos.serializers import ProductoSerializer
from productos.models import Producto

class EstadoVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoVenta
        fields = '__all__'


class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'


class OrdenVentaProductoSerializer(serializers.ModelSerializer):
    # Campos read-only para mostrar el objeto completo
    producto = ProductoSerializer(source='id_producto', read_only=True)

    # Campos write-only para crear la relación con IDs
    id_orden_venta = serializers.PrimaryKeyRelatedField(
        queryset=OrdenVenta.objects.all(), write_only=True
    )
    id_producto = serializers.PrimaryKeyRelatedField(
        queryset=Producto.objects.all(), write_only=True
    )

    class Meta:
        model = OrdenVentaProducto
        fields = [
            "id_orden_venta_producto",
            "cantidad",
            "producto",
            "id_orden_venta",
            "id_producto"
        ]

    def create(self, validated_data):
        orden_venta = validated_data.pop("id_orden_venta")
        producto = validated_data.pop("id_producto")
        return OrdenVentaProducto.objects.create(
            **validated_data, id_orden_venta=orden_venta, id_producto=producto
        )


class OrdenVentaSerializer(serializers.ModelSerializer):
    cliente = ClienteSerializer(source='id_cliente', read_only=True)
    estado_venta = EstadoVentaSerializer(source='id_estado_venta', read_only=True)

    # Campos write-only para POST/PUT
    id_cliente = serializers.PrimaryKeyRelatedField(
        queryset=Cliente.objects.all(), write_only=True
    )
    id_estado_venta = serializers.PrimaryKeyRelatedField(
        queryset=EstadoVenta.objects.all(), write_only=True
    )

    productos = OrdenVentaProductoSerializer(
        source='ordenventaproducto_set',  # related_name por defecto
        many=True,
        read_only=True
    )

    class Meta:
        model = OrdenVenta
        fields = [
            "id_orden_venta",
            "fecha",
            "cliente",
            "estado_venta",
            "productos",
            "id_cliente",
            "id_estado_venta",
        ]

class OrdenVentaProductoSerializer(serializers.ModelSerializer):
    # Campos read-only para mostrar el objeto completo
    orden_venta = OrdenVentaSerializer(source='id_orden_venta', read_only=True)
    producto = ProductoSerializer(source='id_producto', read_only=True)

    # Campos write-only para crear la relación con IDs
    id_orden_venta = serializers.PrimaryKeyRelatedField(
        queryset=OrdenVenta.objects.all(), write_only=True
    )
    id_producto = serializers.PrimaryKeyRelatedField(
        queryset=Producto.objects.all(), write_only=True
    )

    class Meta:
        model = OrdenVentaProducto
        fields = [
            "id_orden_venta_producto",
            "cantidad",
            "orden_venta",   
            "producto",      
            "id_orden_venta",
            "id_producto"   
        ]

    def create(self, validated_data):
        # Separamos los IDs de los objetos relacionados
        orden_venta = validated_data.pop("id_orden_venta")
        producto = validated_data.pop("id_producto")
        return OrdenVentaProducto.objects.create(
            **validated_data, id_orden_venta=orden_venta, id_producto=producto
        )
    


