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

"""
# V1
class LoteProduccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteProduccion
        fields = "__all__"
"""

"""
# V2 
class LoteProduccionSerializer(serializers.ModelSerializer):
    # --- CAMPO AÑADIDO ---
    # Muestra la unidad de medida del producto asociado al lote.
    unidad_medida = serializers.CharField(source='id_producto.id_unidad.descripcion', read_only=True)

    class Meta:
        model = LoteProduccion
        # --- CAMBIO: Listamos los campos explícitamente para incluir el nuevo ---
        fields = [
            'id_lote_produccion',
            'id_producto',
            'fecha_produccion',
            'fecha_vencimiento',
            'cantidad',
            'id_estado_lote_produccion',
            'unidad_medida'  # <-- Campo nuevo añadido a la lista
        ]

"""

# V3
class LoteProduccionSerializer(serializers.ModelSerializer):
    # --- CAMPOS AÑADIDOS PARA ENRIQUECER LA RESPUESTA DE LA API ---

    # 1. Muestra el nombre del producto en lugar de solo su ID.
    producto_nombre = serializers.CharField(source='id_producto.nombre', read_only=True)
    
    # 2. Muestra la unidad de medida del producto asociado. ¡Esta es la clave!
    unidad_medida = serializers.CharField(source='id_producto.id_unidad.descripcion', read_only=True)
    
    # 3. Muestra la descripción del estado del lote en lugar de solo su ID.
    estado = serializers.CharField(source='id_estado_lote_produccion.descripcion', read_only=True)
    
    # 4. Expone las propiedades calculadas 'cantidad_reservada' y 'cantidad_disponible' en la API.
    cantidad_reservada = serializers.ReadOnlyField()
    cantidad_disponible = serializers.ReadOnlyField()

    class Meta:
        model = LoteProduccion
        # Definimos explícitamente los campos que queremos mostrar.
        fields = [
            'id_lote_produccion',
            'id_producto',
            'producto_nombre',   # <-- Nuevo
            'unidad_medida',     # <-- Nuevo
            'fecha_produccion',
            'fecha_vencimiento',
            'cantidad',          # Stock físico
            'cantidad_reservada',# <-- Propiedad
            'cantidad_disponible',# <-- Propiedad
            'id_estado_lote_produccion',
            'estado',            # <-- Nuevo
        ]



class LoteMateriaPrimaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteMateriaPrima
        fields = "__all__"

class LoteProduccionMateriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteProduccionMateria
        fields = "__all__"



class HistoricalLoteProduccionSerializer(serializers.ModelSerializer):
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)
    producto_nombre = serializers.CharField(source='id_producto.nombre', read_only=True)
    estado_lote = serializers.CharField(source='id_estado_lote_produccion.descripcion', read_only=True)

    class Meta:
        model = LoteProduccion.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre',
            'id_lote_produccion', 'id_producto', 'producto_nombre',
            'id_estado_lote_produccion', 'estado_lote',
            'cantidad', 'fecha_produccion', 'fecha_vencimiento'
        ]

class HistoricalLoteMateriaPrimaSerializer(serializers.ModelSerializer):
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)
    materia_prima_nombre = serializers.CharField(source='id_materia_prima.nombre', read_only=True)
    estado_lote = serializers.CharField(source='id_estado_lote_materia_prima.descripcion', read_only=True)

    class Meta:
        model = LoteMateriaPrima.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre',
            'id_lote_materia_prima', 'id_materia_prima', 'materia_prima_nombre',
            'id_estado_lote_materia_prima', 'estado_lote',
            'cantidad', 'fecha_vencimiento'
        ]