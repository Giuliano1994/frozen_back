from django.db import models
from simple_history.models import HistoricalRecords
from productos.models import Producto
from empleados.models import Empleado
from stock.models import LoteProduccion
from ventas.models import OrdenVenta, OrdenVentaProducto

class EstadoOrdenProduccion(models.Model):
    id_estado_orden_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "estado_orden_produccion"

class estado_linea_produccion(models.Model):
    id_estado_linea_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=50)

    class Meta:
        db_table = "estado_linea_produccion"


class LineaProduccion(models.Model):
    id_linea_produccion = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)
    id_estado_linea_produccion = models.ForeignKey(estado_linea_produccion, on_delete=models.CASCADE, db_column="id_estado_linea_produccion")
    capacidad_por_hora = models.FloatField(default=0.0)
    
    class Meta:
        db_table = "linea_produccion"


class OrdenProduccion(models.Model):
    id_orden_produccion = models.AutoField(primary_key=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio = models.DateTimeField(blank=True, null=True)
    fecha_planificada = models.DateTimeField(blank=True, null=True)
    fecha_fin_planificada = models.DateField(null=True, blank=True)
    cantidad = models.IntegerField()
    es_generada_automaticamente = models.BooleanField(
        default=False, 
        help_text="True si fue creada por el MRP. False si fue creada manualmente.",
        null=True
    )
    id_estado_orden_produccion = models.ForeignKey(
        EstadoOrdenProduccion, on_delete=models.CASCADE, db_column="id_estado_orden_produccion"
    )
    """  Comentamos ya que la Orden de Trabajo tendra la relacion con la linea de produccion
    id_linea_produccion = models.ForeignKey(
        LineaProduccion, on_delete=models.SET_NULL, blank=True, null=True, db_column="id_linea_produccion"
    )
    """
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
    # Asociación opcional a la orden de venta que originó esta orden de producción
    id_orden_venta = models.ForeignKey(
        OrdenVenta, on_delete=models.SET_NULL, blank=True, null=True, db_column="id_orden_venta"
    )

    history = HistoricalRecords()
    class Meta:
        db_table = "orden_produccion"



class EstadoOrdenTrabajo(models.Model):
    id_estado_orden_trabajo = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=50)
    # Podrías añadir un campo 'es_final' (Boolean) 
    # para marcar estados como "Completada" o "Cancelada"

    class Meta:
        db_table = "estado_orden_trabajo"
        verbose_name = "Estado de Orden de Trabajo"
        verbose_name_plural = "Estados de Órdenes de Trabajo"

    def __str__(self):
        return self.descripcion
    


class OrdenDeTrabajo(models.Model):
    id_orden_trabajo = models.AutoField(primary_key=True)
    
    # --- Vínculos Clave ---
    id_orden_produccion = models.ForeignKey(
        OrdenProduccion, 
        on_delete=models.CASCADE, 
        db_column="id_orden_produccion",
        related_name="ordenes_de_trabajo"
    )
    id_linea_produccion = models.ForeignKey(
        LineaProduccion, 
        on_delete=models.PROTECT,
        db_column="id_linea_produccion",
        related_name="ordenes_de_trabajo"
    )
    
    # --- Datos de Planificación ---
    cantidad_programada = models.IntegerField()
    hora_inicio_programada = models.DateTimeField()
    hora_fin_programada = models.DateTimeField()

    # --- Seguimiento y Control ---
    id_estado_orden_trabajo = models.ForeignKey(
        EstadoOrdenTrabajo, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        db_column="id_estado_orden_trabajo"
    )
    
    hora_inicio_real = models.DateTimeField(null=True, blank=True)
    hora_fin_real = models.DateTimeField(null=True, blank=True)
    cantidad_producida = models.IntegerField(null=True, blank=True)
    produccion_bruta = models.IntegerField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        db_table = "orden_de_trabajo"
        ordering = ['hora_inicio_programada']

    def __str__(self):
        return f"OT-{self.id_orden_trabajo} (OP: {self.id_orden_produccion.id_orden_produccion})"

    def recalcular_cantidad_producida(self):
        """
        Recalcula la cantidad producida según las no conformidades cargadas.
        """
        from django.db.models import Sum
        
        desperdicio_total = self.no_conformidades.aggregate(
            total=Sum("cant_desperdiciada")
        )["total"] or 0

        self.cantidad_producida = max(self.cantidad_programada - desperdicio_total, 0)
        self.save(update_fields=["cantidad_producida"])
        
    
class TipoNoConformidad(models.Model):
    id_tipo_no_conformidad = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "tipo_no_conformidad"
        verbose_name = "Tipo de No Conformidad"
        verbose_name_plural = "Tipos de No Conformidades"
    
    def __str__(self):
        return self.nombre
    
    
class NoConformidad(models.Model):
    id_no_conformidad = models.AutoField(primary_key=True)

    id_orden_trabajo = models.ForeignKey(
        OrdenDeTrabajo,
        on_delete=models.CASCADE,
        db_column="id_orden_trabajo",
        related_name="no_conformidades"
    )

    id_tipo_no_conformidad = models.ForeignKey(
        TipoNoConformidad,
        on_delete=models.PROTECT,
        db_column="id_tipo_no_conformidad"
    )

    cant_desperdiciada = models.IntegerField()

    class Meta:
        db_table = "no_conformidades"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.id_orden_trabajo.recalcular_cantidad_producida()

    def delete(self, *args, **kwargs):
        ot = self.id_orden_trabajo
        super().delete(*args, **kwargs)
        ot.recalcular_cantidad_producida()


class PausaOT(models.Model):
    id_pausa = models.AutoField(primary_key=True)
    id_orden_trabajo = models.ForeignKey(
        OrdenDeTrabajo, 
        on_delete=models.CASCADE, 
        related_name="pausas"
    )
    motivo = models.CharField(max_length=255)
    
    # Campo para registrar la duración teórica de la pausa
    duracion_minutos = models.IntegerField(default=0) 
    
    # Campo para saber si está activa (pendiente de finalización)
    # Usamos un booleano en lugar de la hora_fin.
    activa = models.BooleanField(default=True) 

    class Meta:
        db_table = "pausa_orden_trabajo"




class OrdenVentaProduccion(models.Model):
    id_orden_venta_produccion = models.AutoField(primary_key=True)

    id_orden_venta = models.ForeignKey(
        'ventas.OrdenVenta',
        on_delete=models.CASCADE,
        db_column='id_orden_venta'
    )

    id_orden_produccion = models.ForeignKey(
        'produccion.OrdenProduccion',
        on_delete=models.CASCADE,
        db_column='id_orden_produccion'
    )

    cantidad_asignada = models.IntegerField(
        null=True, blank=True,
        help_text="Cantidad de productos de esta OP asignada a esta OV (opcional)"
    )

    class Meta:
        db_table = "orden_venta_produccion"
        unique_together = (("id_orden_venta", "id_orden_produccion"),)
        verbose_name = "Relación Orden de Venta - Orden de Producción"
        verbose_name_plural = "Relaciones Orden de Venta - Orden de Producción"

    def __str__(self):
        return f"OV-{self.id_orden_venta_id} ↔ OP-{self.id_orden_produccion_id}"
    
class CalendarioProduccion(models.Model):
    """
    Es una "reserva blanda" (placeholder) creada por el MRP (Fase 1).
    Representa las horas reservadas para una OP en un día y línea.
    """
    id_orden_produccion = models.ForeignKey(OrdenProduccion, on_delete=models.CASCADE, related_name="reservas_calendario")
    id_linea_produccion = models.ForeignKey(LineaProduccion, on_delete=models.CASCADE, related_name="reservas_calendario")
    fecha = models.DateField(db_index=True)
    horas_reservadas = models.DecimalField(max_digits=5, decimal_places=2)
    cantidad_a_producir = models.IntegerField(default=0)

    class Meta:
        unique_together = ('id_linea_produccion', 'fecha', 'id_orden_produccion')

class OrdenProduccionPegging(models.Model):
    """
    Esta es la tabla 'Muchos-a-Muchos' (M-M) que vincula
    qué OPs satisfacen qué líneas de OV.
    """
    id_orden_produccion = models.ForeignKey(
        OrdenProduccion, 
        on_delete=models.CASCADE, 
        related_name="ovs_vinculadas"
    )
    id_orden_venta_producto = models.ForeignKey(
        OrdenVentaProducto, 
        on_delete=models.CASCADE, 
        related_name="ops_vinculadas"
    )
    cantidad_asignada = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ('id_orden_produccion', 'id_orden_venta_producto')