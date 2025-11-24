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
from stock.services import get_stock_disponible_para_producto,  verificar_stock_y_enviar_alerta, get_stock_disponible_todos_los_productos, actualizar_estado_lote_producto
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
    ReservaMateriaPrima,
    ReservaStock
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
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, filters.OrderingFilter]
    search_fields = ["id_producto__nombre"]
    filterset_fields = ["id_producto", "id_estado_lote_produccion", "fecha_produccion", "fecha_vencimiento"]
    ordering = ['-id_lote_produccion']

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
        Cambia el estado del Lote. 
        Si pasa a 'Cuarentena':
           1. Elimina reservas de Productos Terminados (OVs).
           2. Elimina reservas de Materia Prima de la OP.
        También sincroniza el estado de la OP.
        """
        id_nuevo_estado = request.data.get('id_estado_lote_produccion')
        
        if not id_nuevo_estado:
            return Response({"error": "Falta el parámetro 'id_estado_lote_produccion'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lote = self.get_object()
            nuevo_estado_lote = EstadoLoteProduccion.objects.get(pk=id_nuevo_estado)
            
            mensaje_extra = "Estado actualizado."
            mensaje_reservas_pt = ""
            mensaje_reservas_mp = ""

            with transaction.atomic():
                # 1. Actualizamos el Lote de Producción
                lote.id_estado_lote_produccion = nuevo_estado_lote
                lote.save()

                # 🔎 Buscamos la OP asociada AHORA (la necesitamos para borrar MP si es cuarentena)
                op_asociada = OrdenProduccion.objects.filter(id_lote_produccion=lote).first()

                # ===================================================================
                # 🛡️ BLOQUE CUARENTENA: LIMPIEZA TOTAL (PT y MP)
                # ===================================================================
                if nuevo_estado_lote.descripcion.lower() == "cuarentena":
                    
                    # --- A. Limpieza de Reservas de PRODUCTO TERMINADO (OVs) ---
                    reservas_activas_pt = ReservaStock.objects.filter(
                        id_lote_produccion=lote,
                        id_estado_reserva__descripcion="Activa"
                    )
                    cantidad_reservas_pt = reservas_activas_pt.count()
                    
                    if cantidad_reservas_pt > 0:
                        ovs_afectadas = set(reservas_activas_pt.values_list('id_orden_venta_producto__id_orden_venta_id', flat=True))
                        reservas_activas_pt.delete()
                        mensaje_reservas_pt = f" ⚠️ Se eliminaron {cantidad_reservas_pt} reservas de PT (OVs: {list(ovs_afectadas)})."
                        print(mensaje_reservas_pt)

                    # --- B. Limpieza de Reservas de MATERIA PRIMA (OP) ---
                    # 🆕 ESTO ES LO QUE PEDISTE AGREGAR
                    if op_asociada:
                        # Asegúrate de importar ReservaMateriaPrima
                        reservas_activas_mp = ReservaMateriaPrima.objects.filter(
                            id_orden_produccion=op_asociada
                            # Si deseas filtrar solo las activas, descomenta la linea de abajo:
                            # , id_estado_reserva_materia__descripcion="Activa" 
                        )
                        cantidad_reservas_mp = reservas_activas_mp.count()

                        if cantidad_reservas_mp > 0:
                            reservas_activas_mp.delete()
                            mensaje_reservas_mp = f" ☢️ Se eliminaron {cantidad_reservas_mp} reservas de Materia Prima de la OP #{op_asociada.pk}."
                            print(mensaje_reservas_mp)

                # ===================================================================
                # FIN BLOQUE LIMPIEZA
                # ===================================================================

                # 3. Sincronización con Orden de Producción (Cambio de Estado)
                if op_asociada:
                    try:
                        estado_equivalente_op = EstadoOrdenProduccion.objects.get(
                            descripcion__iexact=nuevo_estado_lote.descripcion
                        )
                        
                        if op_asociada.id_estado_orden_produccion != estado_equivalente_op:
                            op_asociada.id_estado_orden_produccion = estado_equivalente_op
                            op_asociada.save()
                            mensaje_extra = f"Se actualizó OP #{op_asociada.pk} a '{estado_equivalente_op.descripcion}'."
                        else:
                            mensaje_extra = "La OP asociada ya tenía ese estado."

                    except EstadoOrdenProduccion.DoesNotExist:
                        mensaje_extra = f"No existe estado equivalente en Producción para '{nuevo_estado_lote.descripcion}'."
                
            return Response({
                "mensaje": "Estado del lote actualizado correctamente.",
                "detalle_op": mensaje_extra,
                "limpieza_pt": mensaje_reservas_pt,
                "limpieza_mp": mensaje_reservas_mp,
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
        id_nuevo_estado = request.data.get('id_estado_lote_materia_prima')
        
        if not id_nuevo_estado:
            return Response({"error": "Debe proporcionar 'id_estado_lote_materia_prima'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lote_mp = self.get_object()
            nuevo_estado_mp = EstadoLoteMateriaPrima.objects.get(pk=id_nuevo_estado)
            mensajes_log = []

            with transaction.atomic():
                # 1. Actualizar Lote MP
                lote_mp.id_estado_lote_materia_prima = nuevo_estado_mp
                lote_mp.save()
                
                # 2. Propagar a Producción
                try:
                    estado_equivalente_prod = EstadoLoteProduccion.objects.get(
                        descripcion__iexact=nuevo_estado_mp.descripcion
                    )
                    
                    # Buscamos en qué OPs se está usando este lote de MP
                    reservas = ReservaMateriaPrima.objects.filter(id_lote_materia_prima=lote_mp).select_related('id_orden_produccion__id_lote_produccion')
                    
                    ids_lotes_prod = set()
                    for r in reservas:
                        # Solo nos interesan OPs que ya generaron un Lote de Producto
                        if r.id_orden_produccion.id_lote_produccion:
                            ids_lotes_prod.add(r.id_orden_produccion.id_lote_produccion.pk)
                    
                    # Obtenemos los objetos LoteProduccion
                    lotes_afectados = LoteProduccion.objects.filter(pk__in=ids_lotes_prod)
                    
                    # Iteramos y aplicamos la función auxiliar (que ahora borra reservas de MP también)
                    for lote_prod in lotes_afectados:
                        if lote_prod.id_estado_lote_produccion != estado_equivalente_prod:
                            msgs = actualizar_estado_lote_producto(lote_prod, estado_equivalente_prod)
                            mensajes_log.extend(msgs)

                    if lotes_afectados.exists():
                        mensajes_log.append(f"Se propagó el estado a {lotes_afectados.count()} lotes de producto terminados.")

                except EstadoLoteProduccion.DoesNotExist:
                    mensajes_log.append("No existe estado equivalente en Productos (no se propagó).")

            return Response({
                "mensaje": "Estado actualizado y propagado.",
                "logs": mensajes_log,
                "nuevo_estado": nuevo_estado_mp.descripcion
            }, status=status.HTTP_200_OK)
            
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
