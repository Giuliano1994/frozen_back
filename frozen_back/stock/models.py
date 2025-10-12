from django.db import models
from productos.models import Producto
from materias_primas.models import MateriaPrima

class EstadoLoteProduccion(models.Model):
    id_estado_lote_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_lote_produccion"


class EstadoLoteMateriaPrima(models.Model):
    id_estado_lote_materia_prima = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_lote_materia_prima"


class LoteProduccion(models.Model):
    id_lote_produccion = models.AutoField(primary_key=True)
    id_producto = models.ForeignKey(Producto, on_delete=models.CASCADE, db_column="id_producto")
    fecha_produccion = models.DateField(blank=True, null=True)
    fecha_vencimiento = models.DateField(blank=True, null=True)
    cantidad = models.IntegerField()
  
    @property
    def cantidad_reservada(self):
        """Calcula la cantidad total reservada para este lote sumando las reservas."""
        # Suma todas las 'cantidad_reservada' de los registros de ReservaStock
        # que apuntan a este lote (self).
        total_reservado = self.reservas.aggregate(
            total=models.Sum('cantidad_reservada')
        )['total']
        return total_reservado or 0

    @property
    def cantidad_disponible(self):
        """Calcula la cantidad real disponible para nuevas reservas."""
        return self.cantidad - self.cantidad_reservada
    
    id_estado_lote_produccion = models.ForeignKey(EstadoLoteProduccion, on_delete=models.CASCADE, db_column="id_estado_lote_produccion")

    class Meta:
        db_table = "lote_produccion"


class LoteMateriaPrima(models.Model):
    id_lote_materia_prima = models.AutoField(primary_key=True)
    id_materia_prima = models.ForeignKey(MateriaPrima, on_delete=models.CASCADE, db_column="id_materia_prima")
    fecha_vencimiento = models.DateField(blank=True, null=True)
    cantidad = models.IntegerField()
    id_estado_lote_materia_prima = models.ForeignKey(EstadoLoteMateriaPrima, on_delete=models.CASCADE, db_column="id_estado_lote_materia_prima")

    @property
    def cantidad_reservada(self):
        """Calcula la cantidad total reservada para este lote sumando las reservas."""
        # Suma todas las 'cantidad_reservada' de los registros de ReservaStock
        # que apuntan a este lote (self).
        total_reservado = self.reservas.aggregate(
            total=models.Sum('cantidad_reservada')
        )['total']
        return total_reservado or 0

    @property
    def cantidad_disponible(self):
        """Calcula la cantidad real disponible para nuevas reservas."""
        return self.cantidad - self.cantidad_reservada

    class Meta:
        db_table = "lote_materia_prima"


class LoteProduccionMateria(models.Model):
    id_lote_produccion_materia = models.AutoField(primary_key=True)
    id_lote_produccion = models.ForeignKey(LoteProduccion, on_delete=models.CASCADE, db_column="id_lote_produccion")
    id_lote_materia_prima = models.ForeignKey(LoteMateriaPrima, on_delete=models.CASCADE, db_column="id_lote_materia_prima")
    cantidad_usada = models.IntegerField()

    class Meta:
        db_table = "lote_produccion_materia"



"""
class ReservaStock(models.Model):
 #    Este modelo vincula una orden de venta con un lote de producción,
#    registrando la cantidad exacta reservada de ese lote para esa orden.
  
    id_reserva = models.AutoField(primary_key=True)
    
    # La línea de la orden que necesita el producto
    id_orden_venta_producto = models.ForeignKey(
        'ventas.OrdenVentaProducto', # Usamos string para evitar importación circular
        on_delete=models.CASCADE,
        related_name="reservas"
    )
    
    # El lote del cual se está reservando el stock
    id_lote_produccion = models.ForeignKey(
        LoteProduccion, 
        on_delete=models.CASCADE,
        related_name="reservas"
    )
    
    # La cantidad reservada en esta transacción específica
    cantidad_reservada = models.PositiveIntegerField()
    
    fecha_reserva = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reserva_stock"
        unique_together = ('id_orden_venta_producto', 'id_lote_produccion')
"""






class EstadoReserva(models.Model):
    id_estado_reserva = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = "estado_reserva"

    def __str__(self):
        return self.descripcion

class ReservaStock(models.Model):
    id_reserva = models.AutoField(primary_key=True)
    id_orden_venta_producto = models.ForeignKey(
        'ventas.OrdenVentaProducto', 
        on_delete=models.CASCADE,
        related_name="reservas"
    )
    id_lote_produccion = models.ForeignKey(
        LoteProduccion, 
        on_delete=models.CASCADE,
        related_name="reservas"
    )
    cantidad_reservada = models.PositiveIntegerField()
    fecha_reserva = models.DateTimeField(auto_now_add=True)

    # --- CAMBIO CLAVE: AÑADIMOS EL ESTADO ---
    id_estado_reserva = models.ForeignKey(
        EstadoReserva,
        on_delete=models.PROTECT
    )

    class Meta:
        db_table = "reserva_stock"
        # Quitamos unique_together para permitir múltiples reservas (ej. una cancelada y una nueva activa)
        # unique_together = ('id_orden_venta_producto', 'id_lote_produccion')

class EstadoReservaMateria(models.Model):
    id_estado_reserva_materia = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_reserva_materia"

    def __str__(self):
        return self.descripcion


class ReservaMateriaPrima(models.Model):
    id_reserva_materia = models.AutoField(primary_key=True)
    id_orden_produccion = models.ForeignKey(
        "produccion.OrdenProduccion",
        on_delete=models.CASCADE,
        db_column="id_orden_produccion"
    )
    id_lote_materia_prima = models.ForeignKey(
        "LoteMateriaPrima",
        on_delete=models.CASCADE,
        db_column="id_lote_materia_prima",
        related_name="reservas"  # 👈 para que funcione cantidad_reservada
    )
    cantidad_reservada = models.IntegerField()
    id_estado_reserva_materia = models.ForeignKey(
        EstadoReservaMateria,
        on_delete=models.CASCADE,
        db_column="id_estado_reserva_materia"
    )

    class Meta:
        db_table = "reserva_materia_prima"

    def __str__(self):
        return f"Reserva {self.id_reserva_materia} - {self.id_lote_materia_prima}"