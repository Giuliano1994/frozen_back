from rest_framework import serializers
from .models import (
    EstadoLoteProduccion,
    EstadoLoteMateriaPrima,
    LoteProduccion,
    LoteMateriaPrima,
    LoteProduccionMateria
)

class EstadoLoteProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoLoteProduccion
        fields = "__all__"

class EstadoLoteMateriaPrimaSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoLoteMateriaPrima
        fields = "__all__"

class LoteProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteProduccion
        fields = "__all__"

class LoteMateriaPrimaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteMateriaPrima
        fields = "__all__"

class LoteProduccionMateriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteProduccionMateria
        fields = "__all__"