from django.db import models

from productos.models import Producto
from empleados.models import Empleado
from stock.models import LoteProduccion

class EstadoOrdenProduccion(models.Model):
    id_estado_orden_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_orden_produccion"


class LineaProduccion(models.Model):
    id_linea_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "linea_produccion"


class OrdenProduccion(models.Model):
    id_orden_produccion = models.AutoField(primary_key=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio = models.DateTimeField(blank=True, null=True)
    cantidad = models.IntegerField()

    id_estado_orden_produccion = models.ForeignKey(
        EstadoOrdenProduccion, on_delete=models.CASCADE, db_column="id_estado_orden_produccion"
    )
    id_linea_produccion = models.ForeignKey(
        LineaProduccion, on_delete=models.SET_NULL, blank=True, null=True, db_column="id_linea_produccion"
    )
    id_supervisor = models.ForeignKey(
        Empleado, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="ordenes_supervisadas", db_column="id_supervisor"
    )
    id_operario = models.ForeignKey(
        Empleado, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="ordenes_operadas", db_column="id_operario"
    )
    id_lote_produccion = models.ForeignKey(
        LoteProduccion, on_delete=models.SET_NULL, blank=True, null=True, db_column="id_lote_produccion"
    )

    id_producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, db_column="id_producto",
        blank=True, null=True
    )

    class Meta:
        db_table = "orden_produccion"


class NoConformidad(models.Model):
    id_no_conformidad = models.AutoField(primary_key=True)
    id_orden_produccion = models.ForeignKey(OrdenProduccion, on_delete=models.CASCADE, db_column="id_orden_produccion")
    descripcion = models.CharField(max_length=100)
    cant_desperdiciada = models.IntegerField()

    class Meta:
        db_table = "no_conformidades"
