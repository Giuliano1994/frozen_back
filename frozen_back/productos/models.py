from django.db import models

class TipoProducto(models.Model):
    id_tipo_producto = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "tipo_producto"


class Unidad(models.Model):
    id_unidad = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = "unidad"


class Producto(models.Model):
    id_producto = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(null=True, blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    id_tipo_producto = models.ForeignKey(TipoProducto, on_delete=models.CASCADE, db_column="id_tipo_producto")
    id_unidad = models.ForeignKey(Unidad, on_delete=models.CASCADE, db_column="id_unidad")
    dias_duracion = models.IntegerField()
    umbral_minimo = models.IntegerField()

    class Meta:
        db_table = "producto"




# Modelo para almacenar imágenes de productos en formato Base64
class ImagenProducto(models.Model):
    id_imagen_producto = models.AutoField(primary_key=True)
    
    # Llave foránea para relacionar con el Producto
    id_producto = models.ForeignKey(
        Producto, 
        on_delete=models.CASCADE, 
        db_column="id_producto",
        related_name="imagenes"  # Esto te permite acceder como: mi_producto.imagenes.all()
    )
    
    # Campo para guardar la imagen en formato Base64
    imagen_base64 = models.TextField(
        null=True, 
        blank=True,
        help_text="Contenido de la imagen codificado en Base64"
    )

    class Meta:
        db_table = "imagen_producto"

    def __str__(self):
        # Es útil para ver un nombre legible en el admin de Django
        return f"Imagen de {self.id_producto.nombre} ({self.id_imagen_producto})"
    






class Combo(models.Model):
    id_combo = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "combo"

    def __str__(self):
        return self.nombre
    

class ComboProducto(models.Model):
    id_combo_producto = models.AutoField(primary_key=True)

    id_combo = models.ForeignKey(
        Combo,
        on_delete=models.CASCADE,
        db_column="id_combo",
        related_name="productos"  # combo.productos.all()
    )

    id_producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        db_column="id_producto"
    )

    cantidad = models.IntegerField(default=1)

    class Meta:
        db_table = "combo_producto"
        unique_together = ("id_combo", "id_producto")

    def __str__(self):
        return f"{self.cantidad} x {self.id_producto.nombre} en combo {self.id_combo.nombre}"