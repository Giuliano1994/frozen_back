from django.db import models
from productos.models import Producto



class Prioridad(models.Model):
    id_prioridad = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "prioridad"


class EstadoVenta(models.Model):
    id_estado_venta = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_venta"


class Cliente(models.Model):
    id_cliente = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100, null=True, blank=True)
    email = models.CharField(max_length=100, unique=True, null=True, blank=True)
    cuil = models.CharField(max_length=100, unique=True, null=True, blank=True)
    contraseña = models.CharField(
        max_length=128, 
        null=True, 
        blank=True,
        help_text="Campo para contraseña (almacenamiento inseguro)"
    )
    id_prioridad = models.ForeignKey(
        Prioridad,
        on_delete=models.SET_NULL, # Si se borra una Prioridad, este campo queda en NULL.
        null=True,                 # Permite que la columna en la BD sea NULL.
        blank=True,                # Permite que en formularios y el admin el campo esté vacío.
        db_column="id_prioridad"
    )


    class Meta:
        db_table = "cliente"

class Reclamo(models.Model):
    id_reclamo = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        db_column="id_cliente"
    )
    fecha_reclamo = models.DateTimeField(auto_now_add=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField()
    estado = models.CharField(max_length=50, default="Abierto")  # Ejemplo de estados: Abierto, En Proceso, Cerrado

    class Meta:
        db_table = "reclamo"

class Sugerencia(models.Model):
    id_sugerencia = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        db_column="id_cliente"
    )
    titulo = models.CharField(max_length=100)
    fecha_sugerencia = models.DateTimeField(auto_now_add=True)
    descripcion = models.TextField()

    class Meta:
        db_table = "sugerencia"



class DireccionCliente(models.Model):
    id_direccion_cliente = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(
        Cliente,  # El modelo Cliente que definiste antes
        on_delete=models.CASCADE,
        db_column="id_cliente",
        related_name="direcciones" # Permite hacer: mi_cliente.direcciones.all()
    )
    calle = models.CharField(max_length=200)
    altura = models.CharField(max_length=50, help_text="Número de la casa, piso, dpto, etc.")
    localidad = models.CharField(max_length=100, null=True, blank=True)
    zona = models.CharField(max_length=10, null=True, blank=True)
    class Meta:
        db_table = "direccion_cliente"



class OrdenVenta(models.Model):

    class TipoVenta(models.TextChoices):
        EMPLEADO = 'EMP', ('Empleado')  # Venta por un empleado
        ONLINE = 'ONL', ('Online')      # Venta por la web

    class TipoZona(models.TextChoices):
        NORTE = 'N', ('Norte')
        SUR = 'S', ('Sur')
        ESTE = 'E', ('Este')
        OESTE = 'O', ('Oeste')

    id_orden_venta = models.AutoField(primary_key=True)
    fecha = models.DateTimeField(auto_now_add=True)
    id_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, db_column="id_cliente")
    id_estado_venta = models.ForeignKey(EstadoVenta, on_delete=models.CASCADE, db_column="id_estado_venta")
    id_prioridad = models.ForeignKey(Prioridad, on_delete=models.CASCADE, db_column="id_prioridad")
    fecha_entrega = models.DateTimeField(null=True, blank=True)
    fecha_estimada = models.DateField(null=True, blank=True)
    # Opcional: empleado asociado a la orden (por ejemplo ventas en mostrador)
    id_empleado = models.ForeignKey(
        'empleados.Empleado',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='id_empleado'
    )
   
    tipo_venta = models.CharField(
        max_length=3,
        choices=TipoVenta.choices,
        default=TipoVenta.EMPLEADO, # O usa 'ONLINE' si ese es tu default
        verbose_name="Tipo de Venta"
    )
    calle = models.CharField(max_length=200, null=True, blank=True)
    altura = models.CharField(max_length=50, help_text="Número de la casa, piso, dpto, etc.", null=True, blank=True)
    localidad = models.CharField(max_length=100, null=True, blank=True)
    # --- CAMPO ZONA MODIFICADO ---
    zona = models.CharField(
        max_length=10, 
        choices=TipoZona.choices, # <--- Agregamos choices
        null=True, 
        blank=True
    )

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




class NotaCredito(models.Model):
    """
    Representa una nota de crédito que anula (total o parcialmente) una factura
    y revierte la operación de stock.
    """
    id_nota_credito = models.AutoField(primary_key=True)
    # Se vincula a la factura, que a su vez tiene la orden de venta
    id_factura = models.OneToOneField(
        Factura, 
        on_delete=models.CASCADE, 
        db_column="id_factura",
        help_text="Factura que esta nota de crédito anula."
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    motivo = models.TextField(blank=True, null=True, help_text="Razón de la nota de crédito (ej. Devolución)")

    class Meta:
        db_table = "nota_credito"

    def __str__(self):
        return f"NC-{self.id_nota_credito} (Factura: {self.id_factura.id_factura})"