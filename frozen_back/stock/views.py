import json
from django.http import JsonResponse
from django.shortcuts import render
from materias_primas.models import MateriaPrima
from stock.models import LoteProduccion
from rest_framework import viewsets, filters
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, action  # <- IMPORT IMPORTANTE
from django_filters.rest_framework import DjangoFilterBackend
from stock.services import get_stock_disponible_para_producto,  verificar_stock_y_enviar_alerta, get_stock_disponible_todos_los_productos
from django.views.decorators.csrf import csrf_exempt
from produccion.services import procesar_ordenes_en_espera
from django.db.models import Sum
from django.db import transaction
from produccion.models import OrdenProduccion, EstadoOrdenProduccion

from django_filters.rest_framework import DjangoFilterBackend
from .models import (
    EstadoLoteProduccion,
    EstadoLoteMateriaPrima,
    LoteProduccion,
    LoteMateriaPrima,
    LoteProduccionMateria,
    ReservaMateriaPrima
)
from .serializers import (
    EstadoLoteProduccionSerializer,
    EstadoLoteMateriaPrimaSerializer,
    LoteProduccionSerializer,
    LoteMateriaPrimaSerializer,
    LoteProduccionMateriaSerializer,
    HistoricalLoteProduccionSerializer, 
    HistoricalLoteMateriaPrimaSerializer
)

# ----- Estados -----
class EstadoLoteProduccionViewSet(viewsets.ModelViewSet):
    queryset = EstadoLoteProduccion.objects.all()
    serializer_class = EstadoLoteProduccionSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["descripcion"]
    filterset_fields = ["descripcion"]

class EstadoLoteMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = EstadoLoteMateriaPrima.objects.all()
    serializer_class = EstadoLoteMateriaPrimaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["descripcion"]
    filterset_fields = ["descripcion"]

# ----- Lotes -----
class LoteProduccionViewSet(viewsets.ModelViewSet):
    queryset = LoteProduccion.objects.all()
    serializer_class = LoteProduccionSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_producto__nombre"]
    filterset_fields = ["id_producto", "id_estado_lote_produccion", "fecha_produccion", "fecha_vencimiento"]

    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        inicio = request.query_params.get('inicio')
        fin = request.query_params.get('fin')

        if not inicio or not fin:
            return Response({"detail": "Se requieren parámetros 'inicio' y 'fin'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            inicio = int(inicio)
            fin = int(fin)
        except ValueError:
            return Response({"detail": "Los parámetros deben ser enteros"}, status=status.HTTP_400_BAD_REQUEST)

        # Ajuste para que funcione aunque los IDs estén en cualquier orden
        orden_min = min(inicio, fin)
        orden_max = max(inicio, fin)

        lotes = LoteProduccion.objects.filter(id_lote_produccion__gte=orden_min,
                                              id_lote_produccion__lte=orden_max)
        count = lotes.count()
        lotes.delete()  # borrará reservas y relaciones en cascada
        return Response({"detail": f"{count} lotes de producción borrados"}, status=status.HTTP_204_NO_CONTENT)
    

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    def cambiar_estado(self, request, pk=None):
        """
        Cambia el estado del Lote de Producción.
        Si este lote está vinculado a una Orden de Producción, busca el estado equivalente
        en Producción y actualiza la Orden también (Trazabilidad hacia atrás).
        """
        id_nuevo_estado = request.data.get('id_estado_lote_produccion')
        
        if not id_nuevo_estado:
            return Response({"error": "Falta el parámetro 'id_estado_lote_produccion'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Obtenemos el lote y el nuevo estado deseado
            lote = self.get_object()
            nuevo_estado_lote = EstadoLoteProduccion.objects.get(pk=id_nuevo_estado)
            
            mensaje_extra = "Solo se actualizó el lote (sin orden vinculada o sin estado equivalente)."

            with transaction.atomic():
                # 2. Actualizamos el Lote de Producción
                lote.id_estado_lote_produccion = nuevo_estado_lote
                lote.save()

                # 3. Buscamos la Orden de Producción asociada (Relación Inversa)
                # Buscamos una OP que tenga este lote asignado en su campo 'id_lote_produccion'
                op_asociada = OrdenProduccion.objects.filter(id_lote_produccion=lote).first()

                if op_asociada:
                    try:
                        # 4. Buscamos el estado equivalente en Producción (por descripción/nombre)
                        # Ej: Si el lote pasa a "Cuarentena", buscamos "Cuarentena" en los estados de OP
                        estado_equivalente_op = EstadoOrdenProduccion.objects.get(
                            descripcion__iexact=nuevo_estado_lote.descripcion
                        )
                        
                        # 5. Actualizamos la OP si el estado es distinto
                        if op_asociada.id_estado_orden_produccion != estado_equivalente_op:
                            op_asociada.id_estado_orden_produccion = estado_equivalente_op
                            op_asociada.save()
                            mensaje_extra = f"Se actualizó también la Orden de Producción #{op_asociada.pk} al estado '{estado_equivalente_op.descripcion}'."
                        else:
                            mensaje_extra = "La Orden de Producción asociada ya tenía ese estado."

                    except EstadoOrdenProduccion.DoesNotExist:
                        mensaje_extra = f"Se actualizó el lote, pero no existe el estado '{nuevo_estado_lote.descripcion}' en el módulo de Producción."
                
            return Response({
                "mensaje": "Estado del lote actualizado correctamente.",
                "detalle": mensaje_extra,
                "nuevo_estado": nuevo_estado_lote.descripcion,
                "id_lote": lote.id_lote_produccion
            }, status=status.HTTP_200_OK)

        except EstadoLoteProduccion.DoesNotExist:
            return Response({"error": "El id_estado_lote_produccion indicado no existe."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
def obtener_lotes_de_materia_prima(request, id_materia_prima):
    lotes = LoteMateriaPrima.objects.filter(id_materia_prima=id_materia_prima)
    serializer = LoteMateriaPrimaSerializer(lotes, many=True)
    return Response(serializer.data)




class LoteMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = LoteMateriaPrima.objects.all()
    serializer_class = LoteMateriaPrimaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, filters.OrderingFilter]
    search_fields = ["id_lote_materia_prima","id_materia_prima__nombre"]
    filterset_fields = ["id_materia_prima", "id_estado_lote_materia_prima", "fecha_vencimiento"]
    ordering = ['-id_lote_materia_prima']



    def perform_create(self, serializer):
        nuevo_lote = serializer.save()
        print(f"Se ha creado un nuevo lote de {nuevo_lote.id_materia_prima.nombre} con cantidad {nuevo_lote.cantidad}.")
        procesar_ordenes_en_espera(nuevo_lote.id_materia_prima)

    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        inicio = request.query_params.get('inicio')
        fin = request.query_params.get('fin')

        if not inicio or not fin:
            return Response({"detail": "Se requieren parámetros 'inicio' y 'fin'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            inicio = int(inicio)
            fin = int(fin)
        except ValueError:
            return Response({"detail": "Los parámetros deben ser enteros"}, status=status.HTTP_400_BAD_REQUEST)

        orden_min = min(inicio, fin)
        orden_max = max(inicio, fin)

        lotes = LoteMateriaPrima.objects.filter(id_lote_materia_prima__gte=orden_min,
                                                id_lote_materia_prima__lte=orden_max)
        count = lotes.count()
        lotes.delete()
        return Response({"detail": f"{count} lotes de materia prima borrados"}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    def cambiar_estado(self, request, pk=None):
        """
        Cambia el estado de un lote de MP.
        Si se encuentra un estado equivalente en Producción, busca las Órdenes de Producción
        donde se reservó esta materia prima y actualiza los Lotes de Producción resultantes.
        """
        id_nuevo_estado = request.data.get('id_estado_lote_materia_prima')
        
        if not id_nuevo_estado:
            return Response({"error": "Debe proporcionar 'id_estado_lote_materia_prima'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lote_mp = self.get_object()
            nuevo_estado_mp = EstadoLoteMateriaPrima.objects.get(pk=id_nuevo_estado)

            with transaction.atomic():
                # 1. Actualizar Lote MP
                lote_mp.id_estado_lote_materia_prima = nuevo_estado_mp
                lote_mp.save()

                mensaje_extra = "Solo se actualizó la materia prima."
                
                # 2. Buscar estado equivalente en Producción
                try:
                    estado_equivalente_prod = EstadoLoteProduccion.objects.get(
                        descripcion__iexact=nuevo_estado_mp.descripcion
                    )
                    
                    # --- NUEVA LÓGICA DE TRAZABILIDAD ---
                    # Buscamos las reservas de este lote de materia prima
                    reservas = ReservaMateriaPrima.objects.filter(
                        id_lote_materia_prima=lote_mp
                    ).select_related('id_orden_produccion')

                    # Recolectamos los IDs de los lotes de producción asociados a esas Órdenes
                    ids_lotes_prod = set()
                    
                    for reserva in reservas:
                        op = reserva.id_orden_produccion
                        # Solo agregamos si la OP ya generó un lote de producción (no es None)
                        if op.id_lote_produccion:
                            ids_lotes_prod.add(op.id_lote_produccion.pk)
                    
                    # Buscamos los objetos LoteProduccion reales
                    lotes_afectados = LoteProduccion.objects.filter(pk__in=ids_lotes_prod)
                    cantidad_afectados = lotes_afectados.count()

                    # Actualizamos uno por uno para asegurar historial
                    for lote_prod in lotes_afectados:
                        # Solo actualizamos si el estado es diferente para evitar spam en historial
                        if lote_prod.id_estado_lote_produccion != estado_equivalente_prod:
                            lote_prod.id_estado_lote_produccion = estado_equivalente_prod
                            lote_prod.save()

                    if cantidad_afectados > 0:
                        mensaje_extra = f"Se actualizaron {cantidad_afectados} lotes de producción asociados (vía Orden de Producción) al estado '{estado_equivalente_prod.descripcion}'."
                    else:
                        mensaje_extra = f"Se actualizó la MP a '{nuevo_estado_mp.descripcion}', pero no se encontraron Lotes de Producción generados asociados."

                except EstadoLoteProduccion.DoesNotExist:
                    mensaje_extra = f"No se encontró un estado de producción equivalente a '{nuevo_estado_mp.descripcion}', solo se actualizó la materia prima."

            return Response({
                "mensaje": "Estado actualizado exitosamente.",
                "detalle": mensaje_extra,
                "nuevo_estado": nuevo_estado_mp.descripcion
            }, status=status.HTTP_200_OK)

        except EstadoLoteMateriaPrima.DoesNotExist:
            return Response({"error": "El estado de materia prima indicado no existe."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class LoteProduccionMateriaViewSet(viewsets.ModelViewSet):
    queryset = LoteProduccionMateria.objects.all()
    serializer_class = LoteProduccionMateriaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_lote_produccion__id_producto__nombre", "id_lote_materia_prima__id_materia_prima__nombre"]
    filterset_fields = ["id_lote_produccion", "id_lote_materia_prima"]



@api_view(["GET"])
def cantidad_total_producto_view(request, id_producto):
    """
    Endpoint que devuelve la cantidad total disponible de un producto.
    """
    total = get_stock_disponible_para_producto(id_producto)
    return Response(
        {"id_producto": id_producto, "cantidad_disponible": total},
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
def lista_cantidad_total_productos_view(request):
    """
    Endpoint que devuelve la cantidad total disponible de TODOS los productos.
    """
    # 1. Llamamos a la nueva función helper
    stock_data = get_stock_disponible_todos_los_productos()
    
    # 2. La función ya devuelve un QuerySet de diccionarios, 
    #    listo para ser serializado por la Response.
    return Response(stock_data, status=status.HTTP_200_OK)



@api_view(["GET"])
def cantidad_total_materia_view(request, id_producto):
    """
    Endpoint que devuelve la cantidad total disponible de un producto.
    """
    total = get_stock_disponible_para_producto(id_producto)
    return Response(
        {"id_producto": id_producto, "cantidad_disponible": total},
        status=status.HTTP_200_OK
    )




@api_view(["GET"])
def verificar_stock_view(request, id_producto):
    """
    Endpoint que verifica stock y envía alerta por correo.
    Recibe parámetro email en query params.
    """
    email = request.query_params.get("email")
    if not email:
        return Response(
            {"error": "Debe especificar el parámetro 'email' en la consulta."},
            status=status.HTTP_400_BAD_REQUEST
        )

    resultado = verificar_stock_y_enviar_alerta(id_producto, email)
    status_code = status.HTTP_200_OK if "error" not in resultado else status.HTTP_404_NOT_FOUND
    return Response(resultado, status=status_code)




@csrf_exempt
def agregar_o_crear_lote(request):
    """
    Agrega cantidad a un lote existente o crea uno nuevo si no existe.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body)
        id_materia_prima = data.get("id_materia_prima")
        cantidad = data.get("cantidad")

        if not id_materia_prima or not cantidad:
            return JsonResponse({"error": "Faltan parámetros (id_materia_prima, cantidad)"}, status=400)

        # Buscar un lote existente
        lote = LoteMateriaPrima.objects.filter(id_materia_prima_id=id_materia_prima).first()

        if lote:
            lote.cantidad += cantidad
            lote.save()
            materia_prima = MateriaPrima.objects.get(pk=data["id_materia_prima"])
            procesar_ordenes_en_espera(materia_prima)
            return JsonResponse({
                "mensaje": "Cantidad agregada al lote existente",
                "id_lote_materia_prima": lote.id_lote_materia_prima,
                "nueva_cantidad": lote.cantidad
            })

        # Buscar o crear estado "Disponible"
        estado, _ = EstadoLoteMateriaPrima.objects.get_or_create(descripcion__iexact="Disponible",
                                                                 defaults={"descripcion": "Disponible"})

        # Crear nuevo lote
        nuevo_lote = LoteMateriaPrima.objects.create(
            id_materia_prima_id=id_materia_prima,
            fecha_vencimiento=None,
            cantidad=cantidad,
            id_estado_lote_materia_prima=estado
        )
        materia_prima = MateriaPrima.objects.get(pk=data["id_materia_prima"])
        procesar_ordenes_en_espera(materia_prima)

        return JsonResponse({
            "mensaje": "Nuevo lote creado",
            "id_lote_materia_prima": nuevo_lote.id_lote_materia_prima,
            "cantidad": nuevo_lote.cantidad
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def restar_cantidad_lote(request):
    """
    Resta una cantidad de materia prima de un lote existente.
    Si no hay suficiente cantidad, devuelve un error.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body)
        id_materia_prima = data.get("id_materia_prima")
        cantidad = data.get("cantidad")

        if not id_materia_prima or not cantidad:
            return JsonResponse({"error": "Faltan parámetros (id_materia_prima, cantidad)"}, status=400)

        lote = LoteMateriaPrima.objects.filter(id_materia_prima_id=id_materia_prima).first()
        if not lote:
            return JsonResponse({"error": "No existe un lote para esa materia prima"}, status=404)

        if lote.cantidad < cantidad:
            return JsonResponse({"error": "Stock insuficiente en el lote"}, status=400)

        lote.cantidad -= cantidad
        lote.save()

        return JsonResponse({
            "mensaje": "Cantidad restada del lote",
            "id_lote_materia_prima": lote.id_lote_materia_prima,
            "cantidad_actual": lote.cantidad
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

#METODO TEMPORAL PARA EL FRONT
def listar_materias_primas(request):
    if request.method != "GET":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # Buscamos el estado "Disponible"
    try:
        estado_disponible = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="disponible")
    except EstadoLoteMateriaPrima.DoesNotExist:
        return JsonResponse({"error": "No existe el estado 'Disponible' en la tabla estado_lote_materia_prima"}, status=500)

    materias = MateriaPrima.objects.all()
    data = []

    for materia in materias:
        # Obtenemos todos los lotes disponibles para esta materia prima
        lotes_disponibles = LoteMateriaPrima.objects.filter(
            id_materia_prima=materia.id_materia_prima,
            id_estado_lote_materia_prima=estado_disponible.id_estado_lote_materia_prima
        )
        
        # Calculamos la suma de cantidad_disponible para todos los lotes
        cantidad_disponible_total = 0
        for lote in lotes_disponibles:
            cantidad_disponible_total += lote.cantidad_disponible
            # cantidad_reservada += lote.cantidad_reservada()

        data.append({
            "id_materia_prima": materia.id_materia_prima,
            "nombre": materia.nombre,
            "unidad_medida": materia.id_unidad.descripcion,
            "umbral_minimo": materia.umbral_minimo,
            "cantidad_disponible": max(cantidad_disponible_total, 0),  # Evitamos valores negativos
        })

    return JsonResponse(data, safe=False)




class HistorialLoteProduccionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para ver el historial de cambios de los Lotes de Producción.
    """
    queryset = LoteProduccion.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalLoteProduccionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_producto', 'id_estado_lote_produccion']
    search_fields = ['history_user__usuario', 'id_producto__nombre']

class HistorialLoteMateriaPrimaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para ver el historial de cambios de los Lotes de Materia Prima.
    """
    queryset = LoteMateriaPrima.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalLoteMateriaPrimaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_materia_prima', 'id_estado_lote_materia_prima']
    search_fields = ['history_user__usuario', 'id_materia_prima__nombre']
