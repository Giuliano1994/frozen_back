from rest_framework import serializers
from .models import TipoProducto, Unidad, Producto, ImagenProducto, Combo, ComboProducto
from productos.models import Producto

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





class ComboProductoSerializer(serializers.ModelSerializer):
    nombre_producto = serializers.CharField(source="id_producto.nombre", read_only=True)

    class Meta:
        model = ComboProducto
        fields = ["id_combo_producto", "id_producto", "nombre_producto", "cantidad"]


class ComboSerializer(serializers.ModelSerializer):
    productos = ComboProductoSerializer(many=True, read_only=True)

    class Meta:
        model = Combo
        fields = ["id_combo", "nombre", "descripcion", "productos"]


class ComboCreateProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComboProducto
        fields = ["id_producto", "cantidad"]


class ComboCreateSerializer(serializers.ModelSerializer):
    productos = ComboCreateProductoSerializer(many=True)

    class Meta:
        model = Combo
        fields = ["id_combo", "nombre", "descripcion", "productos"]

    def create(self, validated_data):
        productos_data = validated_data.pop("productos")
        combo = Combo.objects.create(**validated_data)

        for p in productos_data:
            ComboProducto.objects.create(
                id_combo=combo,
                id_producto=p["id_producto"],
                cantidad=p["cantidad"],
            )

        return combo

    def update(self, instance, validated_data):
        productos_data = validated_data.pop("productos", None)

        instance.nombre = validated_data.get("nombre", instance.nombre)
        instance.descripcion = validated_data.get("descripcion", instance.descripcion)
        instance.save()

        if productos_data is not None:
            # Borrar los productos actuales del combo
            ComboProducto.objects.filter(id_combo=instance).delete()

            # Crear nuevos
            for p in productos_data:
                ComboProducto.objects.create(
                    id_combo=instance,
                    id_producto=p["id_producto"],
                    cantidad=p["cantidad"],
                )

        return instance