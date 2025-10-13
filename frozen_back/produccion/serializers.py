from rest_framework import serializers
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad
from empleados.models import Empleado
from productos.models import Producto
from stock.models import LoteProduccion, EstadoLoteProduccion

# ------------------------------
# Serializers básicos
# ------------------------------
class EstadoOrdenProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoOrdenProduccion
        fields = '__all__'

class LineaProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineaProduccion
        fields = '__all__'

class EmpleadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empleado
        fields = ['id_empleado', 'nombre', 'apellido']

class ProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Producto
        fields = ['id_producto', 'nombre', 'descripcion', 'dias_duracion']

class EstadoLoteProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoLoteProduccion
        fields = ['id_estado_lote_produccion', 'descripcion']

class LoteProduccionSerializer(serializers.ModelSerializer):
    id_estado_lote_produccion = EstadoLoteProduccionSerializer()
    id_producto = ProductoSerializer()

    class Meta:
        model = LoteProduccion
        fields = ['id_lote_produccion', 'id_producto', 'fecha_produccion', 'fecha_vencimiento', 'cantidad', 'id_estado_lote_produccion']

# ------------------------------
# Serializer principal de OrdenProduccion
# ------------------------------

class OrdenProduccionCreateSerializer(serializers.ModelSerializer):
    # Campos que se aceptan como IDs en la entrada pero se devuelven como objetos completos
    id_producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all(), write_only=True)
    id_linea_produccion = serializers.PrimaryKeyRelatedField(queryset=LineaProduccion.objects.all(), write_only=True, required=False)
    id_supervisor = serializers.PrimaryKeyRelatedField(queryset=Empleado.objects.all(), write_only=True, required=False)
    id_operario = serializers.PrimaryKeyRelatedField(queryset=Empleado.objects.all(), write_only=True, required=False)
    
    # Campos de solo lectura que se devuelven como objetos completos
    id_estado_orden_produccion = EstadoOrdenProduccionSerializer(read_only=True)
    id_lote_produccion = LoteProduccionSerializer(read_only=True)
    
    class Meta:
        model = OrdenProduccion
        fields = '__all__'
    
    def validate(self, data):
        # Validar que el producto sea obligatorio
        if not data.get('id_producto'):
            raise serializers.ValidationError("El producto es obligatorio para crear la orden.")
        return data
    
    def to_representation(self, instance):
        # Personalizar la respuesta para devolver objetos completos
        data = super().to_representation(instance)
        
        # Reemplazar los campos write_only con objetos completos
        if instance.id_producto:
            data['id_producto'] = ProductoSerializer(instance.id_producto).data
        if instance.id_linea_produccion:
            data['id_linea_produccion'] = LineaProduccionSerializer(instance.id_linea_produccion).data
        if instance.id_supervisor:
            data['id_supervisor'] = EmpleadoSerializer(instance.id_supervisor).data
        if instance.id_operario:
            data['id_operario'] = EmpleadoSerializer(instance.id_operario).data
            
        return data

class OrdenProduccionSerializer(serializers.ModelSerializer):
    id_estado_orden_produccion = EstadoOrdenProduccionSerializer(read_only=True)
    id_linea_produccion = LineaProduccionSerializer(read_only=True)
    id_supervisor = EmpleadoSerializer(read_only=True)
    id_operario = EmpleadoSerializer(read_only=True)
    id_producto = ProductoSerializer(read_only=True)
    id_lote_produccion = LoteProduccionSerializer(read_only=True)

    class Meta:
        model = OrdenProduccion
        fields = '__all__'

# ------------------------------
# Serializer para actualizar estado de OrdenProduccion
# ------------------------------
class OrdenProduccionUpdateEstadoSerializer(serializers.ModelSerializer):
    id_estado_orden_produccion = serializers.PrimaryKeyRelatedField(
        queryset=EstadoOrdenProduccion.objects.all()
    )
    
    class Meta:
        model = OrdenProduccion
        fields = ['id_estado_orden_produccion']
    
    def validate_id_estado_orden_produccion(self, value):
        if not value:
            raise serializers.ValidationError("El estado de la orden es obligatorio.")
        return value

# ------------------------------
# Serializer de NoConformidad
# ------------------------------
class NoConformidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoConformidad
        fields = '__all__'