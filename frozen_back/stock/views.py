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

from django_filters.rest_framework import DjangoFilterBackend
from .models import (
    EstadoLoteProduccion,
    EstadoLoteMateriaPrima,
    LoteProduccion,
    LoteMateriaPrima,
    LoteProduccionMateria
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


@api_view(["GET"])
def obtener_lotes_de_materia_prima(request, id_materia_prima):
    lotes = LoteMateriaPrima.objects.filter(id_materia_prima=id_materia_prima)
    serializer = LoteMateriaPrimaSerializer(lotes, many=True)
    return Response(serializer.data)




class LoteMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = LoteMateriaPrima.objects.all()
    serializer_class = LoteMateriaPrimaSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["id_materia_prima__nombre"]
    filterset_fields = ["id_materia_prima", "id_estado_lote_materia_prima", "fecha_vencimiento"]


 # --- MÉTODO AÑADIDO ---
    def perform_create(self, serializer):
        """
        Guarda el nuevo lote de materia prima y luego verifica si alguna orden 
        en espera puede ser procesada con este nuevo stock.
        """
        # 1. Guarda el nuevo lote como siempre
        nuevo_lote = serializer.save()
        print(f"Se ha creado un nuevo lote de {nuevo_lote.id_materia_prima.nombre} con cantidad {nuevo_lote.cantidad}.")

        # 2. Llama al servicio para que revise las órdenes pendientes
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
        lotes.delete()  # borrará reservas y relaciones en cascada
        return Response({"detail": f"{count} lotes de materia prima borrados"}, status=status.HTTP_204_NO_CONTENT)




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
