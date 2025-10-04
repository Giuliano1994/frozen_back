from rest_framework import serializers
from .models import Receta, RecetaMateriaPrima
from materias_primas.models import MateriaPrima

# ------------------------------
# Serializer Receta
# ------------------------------
class RecetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receta
        fields = "__all__"

# ------------------------------
# Serializer RecetaMateriaPrima
# ------------------------------
class RecetaMateriaPrimaSerializer(serializers.ModelSerializer):
    # Podemos incluir info de la materia prima
    nombre_materia_prima = serializers.CharField(source='id_materia_prima.nombre', read_only=True)

    class Meta:
        model = RecetaMateriaPrima
        fields = ["id_receta_materia_prima", "id_receta", "id_materia_prima", "nombre_materia_prima", "cantidad"]
