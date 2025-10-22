from rest_framework import serializers
from .models import Proveedor, TipoMateriaPrima, MateriaPrima

# ------------------------------
# Serializer TipoMateriaPrima
# ------------------------------
class TipoMateriaPrimaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoMateriaPrima
        fields = "__all__"

# ------------------------------
# Serializer MateriaPrima
# ------------------------------
class MateriaPrimaSerializer(serializers.ModelSerializer):
    tipo_descripcion = serializers.CharField(source='id_tipo_materia_prima.descripcion', read_only=True)

    class Meta:
        model = MateriaPrima
        fields = [
            "id_materia_prima", "nombre", "descripcion", "precio",
            "id_tipo_materia_prima", "tipo_descripcion", "id_unidad","id_proveedor", "umbral_minimo"
        ]
        
class proveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = "__all__"