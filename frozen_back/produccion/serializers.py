from rest_framework import serializers
from .models import EstadoOrdenProduccion, LineaProduccion, OrdenProduccion, NoConformidad


class EstadoOrdenProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoOrdenProduccion
        fields = '__all__'


class LineaProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineaProduccion
        fields = '__all__'


class OrdenProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdenProduccion
        fields = '__all__'


class NoConformidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoConformidad
        fields = '__all__'