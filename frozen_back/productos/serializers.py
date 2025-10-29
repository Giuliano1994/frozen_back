from rest_framework import serializers
from .models import TipoProducto, Unidad, Producto, ImagenProducto


class TipoProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProducto
        fields = '__all__'


class UnidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unidad
        fields = '__all__'


# NUEVO: Serializador para el modelo de imagen
class ImagenProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagenProducto
        # Solo exponemos la imagen, el ID del producto es implícito
        fields = ['id_imagen_producto', 'imagen_base64']


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





# NUEVO: Serializador de Producto CON imágenes
# Este hereda de ProductoSerializer y solo añade las imágenes
class ProductoDetalleSerializer(ProductoSerializer):
    # Usamos el 'related_name="imagenes"' que definimos en el modelo
    imagenes = ImagenProductoSerializer(many=True, read_only=True)

    class Meta(ProductoSerializer.Meta):
        # Heredamos los fields del padre y agregamos 'imagenes'
        fields = ProductoSerializer.Meta.fields + ['imagenes']