from django.db import models
from productos.models import Producto
from materias_primas.models import MateriaPrima
from produccion.models import  LineaProduccion



class Receta(models.Model):
    id_receta = models.AutoField(primary_key=True)
    id_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, db_column="id_producto")
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "receta"


class RecetaMateriaPrima(models.Model):
    id_receta_materia_prima = models.AutoField(primary_key=True)
    id_receta = models.ForeignKey(Receta, on_delete=models.CASCADE, db_column="id_receta")
    id_materia_prima = models.ForeignKey(MateriaPrima, on_delete=models.CASCADE, db_column="id_materia_prima")
    cantidad = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "receta_materia_prima"

class ProductoLinea(models.Model):
    id_producto_linea = models.AutoField(primary_key=True)
    id_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, db_column="id_producto")
    id_linea_produccion = models.ForeignKey(LineaProduccion, on_delete=models.CASCADE, db_column="id_linea_produccion")
    cant_por_hora = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "producto_linea"
        unique_together = ("id_producto", "id_linea_produccion")
