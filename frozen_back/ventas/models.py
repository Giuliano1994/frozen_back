from django.db import models
from productos.models import Producto

class EstadoVenta(models.Model):
    id_estado_venta = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_venta"


class Cliente(models.Model):
    id_cliente = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    email = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        db_table = "cliente"

class Prioridad(models.Model):
    id_prioridad = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "prioridad"

class OrdenVenta(models.Model):
    id_orden_venta = models.AutoField(primary_key=True)
    fecha = models.DateTimeField(auto_now_add=True)
    id_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, db_column="id_cliente")
    id_estado_venta = models.ForeignKey(EstadoVenta, on_delete=models.CASCADE, db_column="id_estado_venta")
    id_prioridad = models.ForeignKey(Prioridad, on_delete=models.CASCADE, db_column="id_prioridad")
    fecha_entrega = models.DateTimeField(null=True, blank=True)
    fecha_estimada = models.DateField(null=True, blank=True)


    class Meta:
        db_table = "orden_venta"


class OrdenVentaProducto(models.Model):
    id_orden_venta_producto = models.AutoField(primary_key=True)
    id_orden_venta = models.ForeignKey(OrdenVenta, on_delete=models.CASCADE, db_column="id_orden_venta")
    id_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, db_column="id_producto")
    cantidad = models.IntegerField()

    class Meta:
        db_table = "orden_venta_producto"
        unique_together = (("id_orden_venta", "id_producto"),)


# lo que sigue es para las facturas, no es necesario el crud por el momento

class Factura(models.Model):
    id_factura = models.AutoField(primary_key=True)
    id_orden_venta = models.OneToOneField(OrdenVenta, on_delete=models.CASCADE, db_column="id_orden_venta")

    class Meta:
        db_table = "factura"
