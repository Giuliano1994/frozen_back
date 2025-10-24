from rest_framework import serializers
from ventas.models import OrdenVenta
from .models import DespachoOrenVenta, EstadoDespacho, OrdenDespacho, Repartidor

class RepartidorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repartidor
        fields = ['id_repartidor', 'nombre', 'telefono']

class EstadoDespachoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoDespacho
        fields = ['id_estado_despacho', 'descripcion']

class OrdenVentaMiniSerializer(serializers.ModelSerializer):
    # Solo los campos básicos que quieras mostrar
    class Meta:
        model = OrdenVenta
        fields = ['id_orden_venta', 'tipo_venta', 'fecha_entrega']

class DespachoOrdenVentaSerializer(serializers.ModelSerializer):
    id_orden_venta = OrdenVentaMiniSerializer(read_only=True)

    class Meta:
        model = DespachoOrenVenta
        fields = ['id_despacho_orden_venta', 'id_orden_venta', 'id_estado_despacho']

class OrdenDespachoSerializer(serializers.ModelSerializer):
    id_repartidor = RepartidorSerializer()
    id_estado_despacho = EstadoDespachoSerializer()
    ordenes_venta = serializers.SerializerMethodField()

    class Meta:
        model = OrdenDespacho
        fields = ['id_orden_despacho', 'id_estado_despacho', 'fecha_despacho', 'id_repartidor', 'ordenes_venta']

    def get_ordenes_venta(self, obj):
        despachos = DespachoOrenVenta.objects.filter(id_orden_despacho=obj)
        return DespachoOrdenVentaSerializer(despachos, many=True).data
    
    
class CrearOrdenDespachoSerializer(serializers.Serializer):
    repartidor = RepartidorSerializer()
    id_estado_despacho = serializers.PrimaryKeyRelatedField(
        queryset=EstadoDespacho.objects.all(),
        required=False,
        allow_null=True
    )
    ordenes_venta = serializers.ListField(child=serializers.IntegerField())

    def create(self, validated_data):
        from django.db import transaction
        from ventas.models import OrdenVenta, EstadoVenta  # para cambiar estado de la orden de venta

        with transaction.atomic():
            # --- 1️⃣ Crear repartidor ---
            repartidor_data = validated_data.pop('repartidor')
            repartidor = Repartidor.objects.create(**repartidor_data)

            # --- 2️⃣ Crear orden de despacho ---
            # Estado de despacho por defecto: "En Reparto"
            estado = validated_data.get('id_estado_despacho')
            if estado is None:
                estado, _ = EstadoDespacho.objects.get_or_create(descripcion="En Reparto")

            orden_despacho = OrdenDespacho.objects.create(
                id_repartidor=repartidor,
                id_estado_despacho=estado
            )

            # --- 3️⃣ Vincular órdenes de venta ---
            ordenes_ids = validated_data.get('ordenes_venta', [])
            for orden_id in ordenes_ids:
                orden_venta = OrdenVenta.objects.get(pk=orden_id)

                # Cambiar el estado de la orden de venta a "Despachando"
                estado_despachando, _ = EstadoVenta.objects.get_or_create(descripcion="Despachando")
                orden_venta.id_estado_venta = estado_despachando
                orden_venta.save()

                # Crear relación despacho-orden-venta
                DespachoOrenVenta.objects.create(
                    id_orden_despacho=orden_despacho,
                    id_orden_venta=orden_venta,
                    id_estado_despacho=estado
                )

            return orden_despacho




class HistoricalOrdenDespachoSerializer(serializers.ModelSerializer):
    history_user_nombre = serializers.CharField(source='history_user.usuario', read_only=True)
    estado_despacho = serializers.CharField(source='id_estado_despacho.descripcion', read_only=True)
    repartidor_nombre = serializers.CharField(source='id_repartidor.nombre', read_only=True)

    class Meta:
        model = OrdenDespacho.history.model
        fields = [
            'history_id', 'history_date', 'history_type', 'history_user_nombre', 
            'id_estado_despacho', 'estado_despacho', 
            'id_repartidor', 'repartidor_nombre', 
            'fecha_despacho'
        ]