import json
from django.shortcuts import render
from rest_framework import viewsets, filters
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from stock.models import LoteProduccion  # según tu estructura
from django.db import models
from rest_framework import status
from .services import gestionar_stock_y_estado_para_orden_venta, cancelar_orden_venta, facturar_orden_y_descontar_stock 
from .models import Factura, OrdenVenta
from django.db import transaction
from .filters import OrdenVentaFilter

from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto, Prioridad
from .serializers import (
    EstadoVentaSerializer,
    ClienteSerializer,
    OrdenVentaSerializer,
    OrdenVentaProductoSerializer,
    PrioridadSerializer,
)

class EstadoVentaViewSet(viewsets.ModelViewSet):
    queryset = EstadoVenta.objects.all()
    serializer_class = EstadoVentaSerializer


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer


class PrioridadViewSet(viewsets.ModelViewSet):
    queryset = Prioridad.objects.all()
    serializer_class = PrioridadSerializer


class OrdenVentaViewSet(viewsets.ModelViewSet):
    queryset = OrdenVenta.objects.all().order_by('-fecha')
    serializer_class = OrdenVentaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OrdenVentaFilter
    search_fields = ['id_cliente__nombre', 'id_estado_venta__descripcion', 'id_prioridad__descripcion']
    ordering_fields = ['fecha', 'fecha_entrega']
    ordering = ['-fecha']


"""
def actualizar_estado_orden(orden):
    from stock.models import LoteProduccion
    productos_orden = OrdenVentaProducto.objects.filter(id_orden_venta=orden)

    if not productos_orden.exists():
        # Sin productos → estado Creada
        estado = EstadoVenta.objects.filter(descripcion__iexact="Creada").first()
    else:
        hay_stock_para_todos = True

        # Primero verificamos si hay stock suficiente para todos los productos
        for op in productos_orden:
            cantidad_disponible = (
                LoteProduccion.objects
                .filter(
                    id_producto=op.id_producto,
                    id_estado_lote_produccion__descripcion="Disponible"
                )
                .aggregate(total=models.Sum("cantidad"))
                .get("total") or 0
            )
            if cantidad_disponible < op.cantidad:
                hay_stock_para_todos = False
                break

        if hay_stock_para_todos:
            # Si hay stock suficiente, se descuenta por lotes (los más próximos a vencer primero)
            for op in productos_orden:
                cantidad_a_descontar = op.cantidad
                lotes = (
                    LoteProduccion.objects
                    .filter(
                        id_producto=op.id_producto,
                        id_estado_lote_produccion__descripcion="Disponible",
                        cantidad__gt=0
                    )
                    .order_by("fecha_vencimiento")  # primero los que vencen antes
                )

                for lote in lotes:
                    if cantidad_a_descontar <= 0:
                        break

                    if lote.cantidad >= cantidad_a_descontar:
                        lote.cantidad -= cantidad_a_descontar
                        cantidad_a_descontar = 0
                    else:
                        cantidad_a_descontar -= lote.cantidad
                        lote.cantidad = 0

                    # Guardamos cambios
                    lote.save(update_fields=["cantidad"])

                    # Si el lote llega a cero, cambiar su estado a Cancelado (id_estado_lote_produccion = 9)
                    if lote.cantidad == 0:
                        lote.id_estado_lote_produccion_id = 9
                        lote.save(update_fields=["id_estado_lote_produccion"])

            # Cambia el estado a “Pendiente de Pago”
            estado = EstadoVenta.objects.filter(descripcion__iexact="Pendiente de Pago").first()
            if not estado:
                estado = EstadoVenta.objects.create(descripcion="Pendiente de Pago")
        else:
            # Si no hay stock suficiente, pasa a “En Preparación”
            estado = EstadoVenta.objects.filter(descripcion__iexact="En Preparación").first()
            if not estado:
                estado = EstadoVenta.objects.create(descripcion="En Preparación")

    if estado:
        orden.id_estado_venta = estado
        orden.save(update_fields=['id_estado_venta'])
"""


class OrdenVentaProductoViewSet(viewsets.ModelViewSet):
    queryset = OrdenVentaProducto.objects.all()
    serializer_class = OrdenVentaProductoSerializer
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        orden_id = response.data.get("id_orden_venta")
        orden = OrdenVenta.objects.get(pk=orden_id)
        
        # Llamamos al único servicio que gestiona todo
        gestionar_stock_y_estado_para_orden_venta(orden)
        
        # Devolvemos la orden actualizada
        orden_serializer = OrdenVentaSerializer(orden)
        return Response(orden_serializer.data, status=status.HTTP_201_CREATED)


    def destroy(self, request, *args, **kwargs):
        """
        Elimina un producto de una orden y recalcula el estado y las reservas.
        """
        # 1. Obtenemos una referencia a la orden ANTES de borrar el producto
        instance = self.get_object()
        orden = instance.id_orden_venta

        # 2. Borramos el producto de la orden.
        # Gracias a on_delete=CASCADE, esto también borra las Reservas de Stock asociadas.
        self.perform_destroy(instance)

        # 3. Re-ejecutamos nuestro servicio para que recalcule todo con los productos restantes.
        print(f"Producto eliminado de la orden #{orden.pk}. Re-evaluando estado y stock...")
        gestionar_stock_y_estado_para_orden_venta(orden)

        # 4. Devolvemos una respuesta vacía, como es estándar en DELETE.
        return Response(status=status.HTTP_204_NO_CONTENT)



"""
# METODO VIEJO

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        orden_producto = serializer.save()
        actualizar_estado_orden(orden_producto.id_orden_venta)
        return Response(self.get_serializer(orden_producto).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        orden = instance.id_orden_venta
        self.perform_destroy(instance)
        actualizar_estado_orden(orden)
        return Response(status=status.HTTP_204_NO_CONTENT)
"""

@api_view(['GET'])
def detalle_orden_venta(request, orden_id):
    """
    Devuelve los productos (detalle) de una orden de venta por su ID.
    """
    detalle = OrdenVentaProducto.objects.filter(id_orden_venta_id=orden_id)
    serializer = OrdenVentaProductoSerializer(detalle, many=True)
    return Response(serializer.data)




@csrf_exempt
def actualizar_orden_venta(request):
    print("Llegó a la función actualizar_orden_venta")
    if request.method == "PUT":
        try:
            data = json.loads(request.body)

            # --- LÍNEAS FALTANTES AÑADIDAS AQUÍ ---
            id_orden_venta = data.get("id_orden_venta")
            if not id_orden_venta:
                return JsonResponse({"error": "El campo 'id_orden_venta' es obligatorio"}, status=400)
            # --- FIN DE LA CORRECCIÓN ---

            with transaction.atomic():
                # Ahora 'id_orden_venta' ya existe y se puede usar aquí
                ordenVenta = OrdenVenta.objects.get(pk=id_orden_venta)
                
                # ... (el resto de tu código para actualizar, eliminar y crear productos)
                
                # Volvemos a ejecutar el servicio para que re-evalue todo
                gestionar_stock_y_estado_para_orden_venta(ordenVenta)

            # Armar la respuesta
            serializer = OrdenVentaSerializer(ordenVenta)
            return JsonResponse(serializer.data, status=200)

        except OrdenVenta.DoesNotExist:
            return JsonResponse({"error": "Orden de venta no encontrada"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405)





@api_view(['POST'])
def cancelar_orden_view(request, orden_id):
        """
        Endpoint para cancelar una orden de venta.
        Libera el stock y actualiza el estado.
        """
        try:
            orden = OrdenVenta.objects.get(pk=orden_id)
            cancelar_orden_venta(orden)
            serializer = OrdenVentaSerializer(orden)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except OrdenVenta.DoesNotExist:
            return Response({"error": "Orden de venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)




@csrf_exempt
def listar_ordenes_venta(request):
    if request.method == "GET":
        try:
            ordenes = OrdenVenta.objects.all().order_by("-fecha")

            data = []
            for orden in ordenes:
                productos = [
                    {
                        "id_producto": op.id_producto.id_producto,
                        "producto": op.id_producto.nombre,
                        "tipo": op.id_producto.id_tipo_producto.descripcion if op.id_producto.id_tipo_producto else None,
                        "unidad": op.id_producto.id_unidad.descripcion if op.id_producto.id_unidad else None,
                        "cantidad": op.cantidad
                    }
                    for op in OrdenVentaProducto.objects.filter(id_orden_venta=orden)
                ]

                data.append({
                    "id_orden_venta": orden.id_orden_venta,
                    "fecha": orden.fecha.strftime("%Y-%m-%d %H:%M:%S") if orden.fecha else None,
                    "fecha_entrega": orden.fecha_entrega.strftime("%Y-%m-%d %H:%M:%S") if orden.fecha_entrega else None,
                    "prioridad": orden.id_prioridad.descripcion,
                    "cliente": orden.id_cliente.nombre if orden.id_cliente else None,
                    "estado_venta": orden.id_estado_venta.descripcion if orden.id_estado_venta else None,
                    "productos": productos
                })

            return JsonResponse(data, safe=False, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405)



@csrf_exempt
def crear_orden_venta(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            estado_creada = EstadoVenta.objects.get(descripcion__iexact="Creada")

            with transaction.atomic(): # Envolvemos todo en una transacción
                orden_venta = OrdenVenta.objects.create(
                    id_cliente_id=data.get("id_cliente"),
                    id_estado_venta=estado_creada,
                    id_prioridad_id=data.get("id_prioridad"),
                    fecha_entrega=data.get("fecha_entrega")
                )

                productos = data.get("productos", [])
                for p in productos:
                    OrdenVentaProducto.objects.create(
                        id_orden_venta=orden_venta,
                        id_producto_id=p["id_producto"],
                        cantidad=p["cantidad"]
                    )

                # LLAMADA ÚNICA AL SERVICIO ORQUESTADOR
                gestionar_stock_y_estado_para_orden_venta(orden_venta)

            # Devolvemos la orden con su estado final y todos sus datos
            serializer = OrdenVentaSerializer(orden_venta)
            return JsonResponse(serializer.data, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    
    return JsonResponse({"error": "Método no permitido"}, status=405)


"""
# METODO VIEJO
@csrf_exempt
def crear_orden_venta(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            # Crear la orden de venta
            ordenVenta = OrdenVenta.objects.create(
                id_cliente_id=data.get("id_cliente"),
                id_estado_venta_id=8,  # estado por defecto
                id_prioridad_id=data.get("id_prioridad"),
                fecha_entrega = data.get("fecha_entrega")
            )

            productos = data.get("productos", [])

            for p in productos:
                OrdenVentaProducto.objects.create(
                    id_orden_venta=ordenVenta,
                    id_producto_id=p["id_producto"],
                    cantidad=p["cantidad"]
                )

            actualizar_estado_orden(ordenVenta)

            # Armar respuesta con toda la información
            orden_data = {
                "id_orden_venta": ordenVenta.id_orden_venta,
                "cliente": {
                    "id": ordenVenta.id_cliente.id_cliente,
                    "nombre": ordenVenta.id_cliente.nombre
                },
                "prioridad": ordenVenta.id_prioridad.descripcion,
                "fecha_entrega": ordenVenta.fecha_entrega,
                "estado": {
                    "id": ordenVenta.id_estado_venta.id_estado_venta,
                    "descripcion": ordenVenta.id_estado_venta.descripcion
                },
                "productos": [
                    {
                        "id": op.id_producto.id_producto,
                        "nombre": op.id_producto.nombre,
                        "cantidad": op.cantidad
                    }
                    for op in OrdenVentaProducto.objects.filter(id_orden_venta=ordenVenta)
                ]
            }

            return JsonResponse(orden_data, status=201, safe=False)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405) 
"""
    

@csrf_exempt
def obtener_facturacion(request, id_orden_venta):
    print("Llegó a la función obtener_facturacion")
    if request.method == "GET":
        try:
            # Buscar orden de venta
            orden = OrdenVenta.objects.select_related("id_cliente", "id_estado_venta", "id_prioridad").get(pk=id_orden_venta)
        except OrdenVenta.DoesNotExist:
            return JsonResponse({"error": "No se encontró la orden de venta"}, status=404)



            # --- MODIFICACIÓN TEMPORAL PARA PRUEBAS ---
            # Verificamos si la orden no está ya facturada para evitar re-procesar
        if orden.id_estado_venta.descripcion.lower() != 'facturada':
            print("--- PRUEBA LOCAL: Cambiando estado a 'Facturada' y descontando stock ---")
            facturar_orden_y_descontar_stock(orden)
            # Volvemos a cargar la orden desde la BBDD para que refleje el nuevo estado "Facturada" en la respuesta
            orden.refresh_from_db()
            # --- FIN DE LA MODIFICACIÓN ---



        # Buscar factura (si existe)
        factura, creada = Factura.objects.get_or_create(id_orden_venta=orden)

        # Obtener productos asociados
        productos = OrdenVentaProducto.objects.select_related("id_producto").filter(id_orden_venta=orden)

        productos_data = []
        total = 0
        for p in productos:
            precio = getattr(p.id_producto, "precio", None)
            subtotal = precio * p.cantidad if precio is not None else None
            if subtotal:
                total += subtotal

            productos_data.append({
                "producto": p.id_producto.nombre,
                "cantidad": p.cantidad,
                "precio_unitario": precio,
                "subtotal": subtotal
            })

        data = {
            "empresa": {
                "nombre": settings.EMPRESA_NOMBRE,
                "cuit": settings.EMPRESA_CUIT,
                "direccion": settings.EMPRESA_DIRECCION,
                "telefono": settings.EMPRESA_TELEFONO,
                "email": settings.EMPRESA_MAIL
            },
            "factura": {
                "id_factura": factura.id_factura if factura else None,
                "id_orden_venta": orden.id_orden_venta,
                "fecha": orden.fecha,
                "estado_venta": orden.id_estado_venta.descripcion,
                "prioridad": orden.id_prioridad.descripcion,
                "fecha_entrega": orden.fecha_entrega
            },
            "cliente": {
                "nombre": orden.id_cliente.nombre,
                "email": orden.id_cliente.email
            },
            "productos": productos_data,
            "total": total if total else "No disponible"
        }


        return JsonResponse(data, safe=False, json_dumps_params={"ensure_ascii": False})

    return JsonResponse({"error": "Método no permitido"}, status=405)



@api_view(['PUT'])
def cambiar_estado_orden_venta(request):
    """
    Endpoint para cambiar el estado de una orden de venta.
    Ejecuta la lógica de stock correspondiente para 'Facturada' o 'Cancelada'.
    """
    try:
        id_orden_venta = request.data.get("id_orden_venta")
        id_nuevo_estado = request.data.get("id_estado_venta")

        if not id_orden_venta or not id_nuevo_estado:
            return Response({"error": "Se requieren 'id_orden_venta' e 'id_estado_venta'."}, status=status.HTTP_400_BAD_REQUEST)

        orden = OrdenVenta.objects.get(pk=id_orden_venta)
        nuevo_estado = EstadoVenta.objects.get(pk=id_nuevo_estado)

        # --- LÓGICA CORREGIDA ---
        if nuevo_estado.descripcion.lower() == 'facturada':
            # Si el estado es "Facturada", llamamos al servicio de descuento físico.
            facturar_orden_y_descontar_stock(orden)
            
        elif nuevo_estado.descripcion.lower() == 'cancelada':
            # --- CAMBIO CLAVE AÑADIDO ---
            # Si el estado es "Cancelada", llamamos al servicio de cancelación.
            cancelar_orden_venta(orden)
            # --- FIN DEL CAMBIO ---
            
        else:
            # Para cualquier otro cambio de estado que no afecta el stock (ej. Pendiente -> En Preparación),
            # simplemente lo actualizamos.
            orden.id_estado_venta = nuevo_estado
            orden.save()
        
        # 'orden' se actualiza dentro del servicio, así que el serializer mostrará el estado final.
        serializer = OrdenVentaSerializer(orden)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except (OrdenVenta.DoesNotExist, EstadoVenta.DoesNotExist):
        return Response({"error": "Orden o Estado no encontrado."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


"""

@api_view(['PUT'])
def cambiar_estado_orden_venta(request):
    
    #Endpoint para cambiar el estado de una orden de venta.
    #Espera un JSON con:
    #{
    #    "id_orden_venta": <int>,
    #    "id_estado_venta": <int>
    #}
    
    try:
        id_orden_venta = request.data.get("id_orden_venta")

        if not id_orden_venta:
            return Response({"error": "El campo 'id_orden_venta' es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        orden = OrdenVenta.objects.get(pk=id_orden_venta)
        cancelar_orden_venta(orden)
        serializer = OrdenVentaSerializer(orden)

        return Response(serializer.data, status=status.HTTP_200_OK)

    except OrdenVenta.DoesNotExist:
        return Response({"error": "Orden de venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

"""