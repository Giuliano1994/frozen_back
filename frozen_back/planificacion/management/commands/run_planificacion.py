
from django.core.management.base import BaseCommand
import os
import sys
from datetime import date, timedelta, datetime
from django.db.models import Sum
from django.db import transaction
from collections import defaultdict
from django.db.utils import IntegrityError

# Agrega la raíz del proyecto al sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ventas.models import OrdenVenta, OrdenVentaProducto
from stock.models import LoteProduccion, ReservaStock, EstadoReserva, LoteMateriaPrima, ReservaMateriaPrima, EstadoReservaMateria
from produccion.models import OrdenProduccion, EstadoOrdenProduccion, LineaProduccion
from recetas.models import Receta, RecetaMateriaPrima, ProductoLinea
from materias_primas.models import Proveedor
from compras.models import OrdenCompra, OrdenCompraMateriaPrima, EstadoOrdenCompra

class Command(BaseCommand):
    help = 'Ejecuta la planificación de órdenes de venta para la próxima semana'

    def handle(self, *args, **options):

        fecha_hoy = date.today()
        fecha_inicio = fecha_hoy
        fecha_fin = fecha_inicio + timedelta(days=7)

        ordenes = OrdenVenta.objects.filter(
            fecha_entrega__date__range=(fecha_inicio, fecha_fin)
        )

        necesidades_por_proveedor = defaultdict(lambda: defaultdict(int))

        if ordenes.exists():
            self.stdout.write(self.style.SUCCESS(f"Planificación de órdenes de venta ({fecha_inicio} a {fecha_fin}):"))
            for orden in ordenes:
                with transaction.atomic():
                    self.stdout.write(self.style.SUCCESS(f"\\n- Orden de Venta ID: {orden.id_orden_venta}, Fecha de Entrega: {orden.fecha_entrega.strftime('%Y-%m-%d')}"))

                    productos_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden)

                    for producto_orden in productos_orden:
                        producto = producto_orden.id_producto
                        cantidad_requerida = producto_orden.cantidad

                        self.stdout.write(self.style.SUCCESS(f"  - Producto: {producto.nombre}, Cantidad Requerida: {cantidad_requerida}"))

                        lotes_disponibles = LoteProduccion.objects.filter(
                            id_producto=producto
                        ).order_by('fecha_vencimiento')

                        stock_disponible_total = sum(lote.cantidad_disponible for lote in lotes_disponibles)

                        self.stdout.write(self.style.SUCCESS(f"    - Stock disponible: {stock_disponible_total}"))

                        cantidad_a_reservar = min(cantidad_requerida, stock_disponible_total)
                        if cantidad_a_reservar > 0:
                            self.stdout.write(self.style.SUCCESS(f"    - Reservando {cantidad_a_reservar} unidades de stock disponible."))
                            estado_reserva, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")

                            cantidad_restante_a_reservar = cantidad_a_reservar
                            for lote in lotes_disponibles:
                                if cantidad_restante_a_reservar <= 0:
                                    break

                                cantidad_en_lote = lote.cantidad_disponible
                                cantidad_reservada_en_lote = min(cantidad_restante_a_reservar, cantidad_en_lote)

                                if cantidad_reservada_en_lote > 0:
                                    ReservaStock.objects.create(
                                        id_orden_venta_producto=producto_orden,
                                        id_lote_produccion=lote,
                                        cantidad_reservada=cantidad_reservada_en_lote,
                                        id_estado_reserva=estado_reserva
                                    )
                                    self.stdout.write(self.style.SUCCESS(f"      - Reservados {cantidad_reservada_en_lote} del lote {lote.id_lote_produccion}"))
                                    cantidad_restante_a_reservar -= cantidad_reservada_en_lote

                        if stock_disponible_total < cantidad_requerida:
                            cantidad_a_producir = cantidad_requerida - stock_disponible_total
                            self.stdout.write(self.style.WARNING(f"    - Stock insuficiente. Se necesitan producir {cantidad_a_producir} unidades."))

                            try:
                                producto_linea = ProductoLinea.objects.filter(id_producto=producto).order_by('-cant_por_hora').first()
                                if not (producto_linea and producto_linea.cant_por_hora > 0):
                                    self.stdout.write(self.style.WARNING(f"      - No se encontró información de producción o la capacidad es 0 para el producto {producto.nombre}"))
                                    continue

                                capacidad_por_hora = producto_linea.cant_por_hora
                                tiempo_produccion_dias = (cantidad_a_producir / capacidad_por_hora) / 24
                                fecha_inicio_produccion_dt = orden.fecha_entrega - timedelta(days=tiempo_produccion_dias)
                                fecha_inicio_produccion = fecha_inicio_produccion_dt.date()

                                self.stdout.write(self.style.SUCCESS(f"      - Fecha de inicio de producción requerida: {fecha_inicio_produccion.strftime('%Y-%m-%d')}"))

                                if fecha_inicio_produccion <= fecha_hoy:
                                    self.stdout.write(self.style.SUCCESS("      - La fecha de inicio de producción es hoy o anterior. Creando orden de producción."))
                                    estado_op, _ = EstadoOrdenProduccion.objects.get_or_create(descripcion="Pendiente")
                                    orden_produccion = OrdenProduccion.objects.create(
                                        id_orden_venta=orden,
                                        id_producto=producto,
                                        cantidad=cantidad_a_producir,
                                        id_estado_orden_produccion=estado_op,
                                        fecha_inicio=fecha_inicio_produccion_dt
                                    )
                                    self.stdout.write(self.style.SUCCESS(f"        - Creada orden de producción por {cantidad_a_producir} unidades."))

                                    receta = Receta.objects.get(id_producto=producto)
                                    receta_materias_primas = RecetaMateriaPrima.objects.filter(id_receta=receta)

                                    for rmp in receta_materias_primas:
                                        materia_prima = rmp.id_materia_prima
                                        cantidad_necesaria_mp = rmp.cantidad * cantidad_a_producir

                                        lotes_mp_disponibles = LoteMateriaPrima.objects.filter(id_materia_prima=materia_prima).order_by('fecha_vencimiento')
                                        stock_mp_disponible = sum(lote.cantidad_disponible for lote in lotes_mp_disponibles)

                                        if stock_mp_disponible >= cantidad_necesaria_mp:
                                            self.stdout.write(self.style.SUCCESS(f"        - Stock de '{materia_prima.nombre}' suficiente. Reservando {cantidad_necesaria_mp} unidades."))
                                            estado_reserva_mp, _ = EstadoReservaMateria.objects.get_or_create(descripcion="Activa")

                                            cantidad_a_reservar_mp = cantidad_necesaria_mp
                                            for lote_mp in lotes_mp_disponibles:
                                                if cantidad_a_reservar_mp <= 0:
                                                    break

                                                cantidad_en_lote_mp = lote_mp.cantidad_disponible
                                                cantidad_reservada_en_lote_mp = min(cantidad_a_reservar_mp, cantidad_en_lote_mp)

                                                if cantidad_reservada_en_lote_mp > 0:
                                                    ReservaMateriaPrima.objects.create(
                                                        id_orden_produccion=orden_produccion,
                                                        id_lote_materia_prima=lote_mp,
                                                        cantidad_reservada=cantidad_reservada_en_lote_mp,
                                                        id_estado_reserva_materia=estado_reserva_mp
                                                    )
                                                    self.stdout.write(self.style.SUCCESS(f"          - Reservados {cantidad_reservada_en_lote_mp} del lote {lote_mp.id_lote_materia_prima}"))
                                                    cantidad_a_reservar_mp -= cantidad_reservada_en_lote_mp
                                        else:
                                            cantidad_a_comprar = cantidad_necesaria_mp - stock_mp_disponible
                                            proveedor = materia_prima.id_proveedor
                                            fecha_limite_compra = fecha_inicio_produccion - timedelta(days=proveedor.lead_time_days)

                                            self.stdout.write(self.style.WARNING(f"        - Stock de '{materia_prima.nombre}' insuficiente. Se necesita comprar {cantidad_a_comprar}."))
                                            self.stdout.write(self.style.SUCCESS(f"          - Fecha límite de compra: {fecha_limite_compra.strftime('%Y-%m-%d')}"))

                                            if fecha_limite_compra <= fecha_hoy:
                                                 self.stdout.write(self.style.SUCCESS("          - La fecha límite de compra es hoy o anterior. Agregando a la orden de compra."))
                                                 necesidades_por_proveedor[proveedor][materia_prima] += cantidad_a_comprar
                                else:
                                    self.stdout.write(self.style.SUCCESS("    - La fecha de inicio de producción es futura. No se requiere acción inmediata."))

                            except Receta.DoesNotExist:
                                self.stdout.write(self.style.ERROR(f"      - No se encontró receta para el producto {producto.nombre}"))

            if necesidades_por_proveedor:
                self.stdout.write(self.style.SUCCESS("\\nCreando órdenes de compra:"))
                try:
                    with transaction.atomic():
                        estado_oc, created = EstadoOrdenCompra.objects.get_or_create(descripcion="Pendiente")
                except IntegrityError:
                    estado_oc = EstadoOrdenCompra.objects.get(descripcion="Pendiente")

                with transaction.atomic():
                    for proveedor, materias_primas in necesidades_por_proveedor.items():
                        fecha_solicitud = fecha_hoy
                        fecha_entrega_estimada = fecha_solicitud + timedelta(days=proveedor.lead_time_days)
                        orden_compra = OrdenCompra.objects.create(
                            id_proveedor=proveedor,
                            id_estado_orden_compra=estado_oc,
                            fecha_solicitud=fecha_solicitud,
                            fecha_entrega_estimada=fecha_entrega_estimada
                        )
                        self.stdout.write(self.style.SUCCESS(f"  - Creada Orden de Compra {orden_compra.id_orden_compra} para el proveedor {proveedor.nombre}"))
                        for materia_prima, cantidad in materias_primas.items():
                            OrdenCompraMateriaPrima.objects.create(id_orden_compra=orden_compra, id_materia_prima=materia_prima, cantidad=cantidad)
                            self.stdout.write(self.style.SUCCESS(f"    - Solicitados {cantidad} de {materia_prima.nombre}"))
            else:
                self.stdout.write(self.style.SUCCESS("\\nNo se requieren órdenes de compra hoy."))
        else:
            self.stdout.write(self.style.SUCCESS("No se encontraron órdenes de venta para la próxima semana."))
