from django.db import models

class estado_orden_compra(models.Model):
    id_estado_orden_compra = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=50)

    class Meta:
        db_table = "estado_orden_compra"

class orden_compra(models.Model):
    id_orden_compra = models.AutoField(primary_key=True)
    id_estado_orden_compra = models.ForeignKey(estado_orden_compra, on_delete=models.CASCADE, db_column="id_estado_orden_compra")
    id_proveedor = models.ForeignKey('materias_primas.Proveedor', on_delete=models.CASCADE, db_column="id_proveedor")
    fecha_solicitud = models.DateField()
    fecha_entrega_estimada = models.DateField()
    fecha_entrega_real = models.DateField(blank=True, null=True)

    class Meta:
        db_table = "orden_compra"

class orden_compra_materia_prima(models.Model):
    id_orden_compra_materia_prima = models.AutoField(primary_key=True)
    id_orden_compra = models.ForeignKey(orden_compra, on_delete=models.CASCADE, db_column="id_orden_compra")
    id_materia_prima = models.ForeignKey('materias_primas.MateriaPrima', on_delete=models.CASCADE, db_column="id_materia_prima")
    cantidad = models.IntegerField()

    class Meta:
        db_table = "orden_compra_materia_prima"
