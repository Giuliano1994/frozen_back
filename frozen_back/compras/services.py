from django.db import transaction
from stock.models import LoteMateriaPrima, EstadoLoteMateriaPrima
from .models import OrdenCompra, EstadoOrdenCompra, OrdenCompraMateriaPrima
from django.utils import timezone

@transaction.atomic
def crear_lotes_materia_prima(orden_compra, materias_recibidas):
    """
    Crea lotes de materia prima a partir de las materias recibidas en una orden de compra.
    
    Args:
        orden_compra: OrdenCompra instance
        materias_recibidas: list of dict with {'id_materia_prima': int, 'cantidad': int}
    """
    # Obtener estado "Disponible" para los lotes
    estado_disponible = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")
    
    lotes_creados = []
    for materia_recibida in materias_recibidas:
        id_materia_prima = materia_recibida['id_materia_prima']
        cantidad = materia_recibida['cantidad']
        
        # Verificar que la materia prima corresponda a la orden
        orden_materia = OrdenCompraMateriaPrima.objects.filter(
            id_orden_compra=orden_compra,
            id_materia_prima_id=id_materia_prima
        ).first()
        
        if not orden_materia:
            raise ValueError(f"La materia prima {id_materia_prima} no pertenece a esta orden de compra")
            
        if cantidad > orden_materia.cantidad:
            raise ValueError(f"La cantidad recibida ({cantidad}) es mayor a la ordenada ({orden_materia.cantidad})")
        
        # Crear el lote
        lote = LoteMateriaPrima.objects.create(
            id_materia_prima_id=id_materia_prima,
            cantidad=cantidad,
            id_estado_lote_materia_prima=estado_disponible,
            fecha_vencimiento=timezone.now().date() + timezone.timedelta(days=180),  # Ajustar según necesidad
        )
        
        lotes_creados.append(lote)
    
    return lotes_creados