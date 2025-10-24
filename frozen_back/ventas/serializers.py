from rest_framework import serializers
from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto, Prioridad, Reclamo, Sugerencia, NotaCredito
from productos.serializers import ProductoSerializer
from productos.models import Producto
from empleados.models import Empleado


class EstadoVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoVenta
        fields = '__all__'


class PrioridadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prioridad
        fields = '__all__'



class ClienteSerializer(serializers.ModelSerializer):
    prioridad = PrioridadSerializer(source='id_prioridad', read_only=True)
    class Meta:
        model = Cliente
        fields = '__all__'

class ReclamoSerializer(serializers.ModelSerializer):
    id_cliente = serializers.PrimaryKeyRelatedField(
        queryset=Cliente.objects.all()
    )

    class Meta:
        model = Reclamo
        fields = [
            "id_reclamo",
            "id_cliente",
            "fecha_reclamo",
            "titulo",
            "descripcion",
            "estado"
        ]

class SugerenciaSerializer(serializers.ModelSerializer):
    id_cliente = serializers.PrimaryKeyRelatedField(
        queryset=Cliente.objects.all(),
    )

    class Meta:
        model = Sugerencia
        fields = [
            "id_sugerencia",
            "id_cliente",
            "fecha_sugerencia",
            "descripcion",
            "titulo"
        ]


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
    prioridad = PrioridadSerializer(source='id_prioridad', read_only=True)

    # Campos write-only para POST/PUT
    id_cliente = serializers.PrimaryKeyRelatedField(
        queryset=Cliente.objects.all(), write_only=True
    )
    id_estado_venta = serializers.PrimaryKeyRelatedField(
        queryset=EstadoVenta.objects.all(), write_only=True
    )
    id_prioridad = serializers.PrimaryKeyRelatedField(
        queryset=Prioridad.objects.all(), write_only=True
    )
    id_empleado = serializers.PrimaryKeyRelatedField(
        queryset=Empleado.objects.all(),
        required=False,
        allow_null=True,
    )


    productos = OrdenVentaProductoSerializer(
        source='ordenventaproducto_set',  # related_name por defecto
        many=True,
        read_only=True
    )

    # Propiedad para ver 'Empleado' u 'Online' en vez de 'EMP' u 'ONL'
    tipo_venta_display = serializers.CharField(source='get_tipo_venta_display', read_only=True)
    
    # Propiedad para ver la dirección formateada
    direccion_entrega_completa = serializers.CharField(read_only=True)

    class Meta:
        model = OrdenVenta
        fields = [
            "id_orden_venta",
            "fecha",
            "fecha_entrega",
            "prioridad", 
            "cliente",
            "estado_venta",
            "productos",
            "id_cliente",
            "id_estado_venta",
            "id_prioridad",
            "id_empleado",
            "tipo_venta",
            "tipo_venta_display",
            "calle",
            "altura", 
            "localidad",
            "zona",
            "direccion_entrega_completa"
        ]

    



class NotaCreditoSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo NotaCredito.
    """
    # Opcional: mostrar más info de la factura
    factura_detalle = serializers.SerializerMethodField()
    
    class Meta:
        model = NotaCredito
        fields = '__all__' # O especifica los campos: ['id_nota_credito', 'id_factura', 'fecha', 'motivo', 'factura_detalle']
        read_only_fields = ['fecha']

    def get_factura_detalle(self, obj):
        # Devuelve info útil de la factura y la orden
        return {
            "id_factura": obj.id_factura.id_factura,
            "id_orden_venta": obj.id_factura.id_orden_venta.id_orden_venta,
            "fecha_orden": obj.id_factura.id_orden_venta.fecha
        }
    

class HistoricalOrdenVentaSerializer(serializers.ModelSerializer):
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)
    estado_venta = serializers.CharField(source='id_estado_venta.descripcion', read_only=True)
    cliente_nombre = serializers.CharField(source='id_cliente.nombre', read_only=True)
    
    class Meta:
        model = OrdenVenta.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre',
            'id_estado_venta', 'estado_venta', 'id_cliente', 'cliente_nombre', 'id_prioridad'
        ]


# (Nuevo Serializer para Historial de NotaCredito)
class HistoricalNotaCreditoSerializer(serializers.ModelSerializer):
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)

    class Meta:
        model = NotaCredito.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre',
            'id_factura', 'motivo'
        ]