from django.db import models
from simple_history.models import HistoricalRecords

class EstadoDespacho(models.Model):
    id_estado_despacho = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_despacho"

class Repartidor(models.Model):
    id_repartidor = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=15)
    patente = models.CharField(max_length=20)

    class Meta:
        db_table = "repartidor"

class OrdenDespacho(models.Model):
    id_orden_despacho = models.AutoField(primary_key=True) 
    id_estado_despacho = models.ForeignKey(EstadoDespacho, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_estado_despacho")
    fecha_despacho = models.DateTimeField(auto_now_add=True)
    id_repartidor = models.ForeignKey(Repartidor, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_repartidor")

    history = HistoricalRecords()
    class Meta:
        db_table = "orden_despacho"

class DespachoOrenVenta(models.Model):
    id_despacho_orden_venta = models.AutoField(primary_key=True)
    id_orden_despacho = models.ForeignKey(OrdenDespacho, on_delete=models.CASCADE, db_column="id_orden_despacho")
    id_orden_venta = models.ForeignKey('ventas.OrdenVenta', on_delete=models.CASCADE, db_column="id_orden_venta")
    id_estado_despacho = models.ForeignKey(EstadoDespacho, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_estado_despacho")

    class Meta:
        db_table = "despacho_orden_venta"
    

