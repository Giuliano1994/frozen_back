import json
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto
from .serializers import (
    EstadoVentaSerializer,
    ClienteSerializer,
    OrdenVentaSerializer,
    OrdenVentaProductoSerializer,
)

class EstadoVentaViewSet(viewsets.ModelViewSet):
    queryset = EstadoVenta.objects.all()
    serializer_class = EstadoVentaSerializer


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer


class OrdenVentaViewSet(viewsets.ModelViewSet):
    queryset = OrdenVenta.objects.all()
    serializer_class = OrdenVentaSerializer


class OrdenVentaProductoViewSet(viewsets.ModelViewSet):
    queryset = OrdenVentaProducto.objects.all()
    serializer_class = OrdenVentaProductoSerializer



@api_view(['GET'])
def detalle_orden_venta(request, orden_id):
    """
    Devuelve los productos (detalle) de una orden de venta por su ID.
    """
    detalle = OrdenVentaProducto.objects.filter(id_orden_venta_id=orden_id)
    serializer = OrdenVentaProductoSerializer(detalle, many=True)
    return Response(serializer.data)


@csrf_exempt
def crear_orden_venta(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            # Crear la orden de venta
            ordenVenta = OrdenVenta.objects.create(
                id_cliente_id=data.get("id_cliente"),
                id_estado_venta_id=3,  # estado por defecto
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


@csrf_exempt
def actualizar_orden_venta(request):
    if request.method == "PUT":
        try:
            data = json.loads(request.body)

            id_orden_venta = data.get("id_orden_venta")
            if not id_orden_venta:
                return JsonResponse({"error": "El campo 'id_orden_venta' es obligatorio"}, status=400)

            # Buscar la orden
            try:
                ordenVenta = OrdenVenta.objects.get(pk=id_orden_venta)
            except OrdenVenta.DoesNotExist:
                return JsonResponse({"error": "Orden de venta no encontrada"}, status=404)
            
            # Actualizar fecha_entrega y prioridad si vienen en el JSON
            fecha_entrega = data.get("fecha_entrega")
            prioridad = data.get("id_prioridad")

            if fecha_entrega:
                ordenVenta.fecha_entrega = fecha_entrega
            if prioridad is not None:  
                ordenVenta.id_prioridad_id = prioridad  

            ordenVenta.save()

            # Eliminar los productos actuales de la orden
            OrdenVentaProducto.objects.filter(id_orden_venta=ordenVenta).delete()

            # Insertar los nuevos productos
            productos = data.get("productos", [])
            for p in productos:
                OrdenVentaProducto.objects.create(
                    id_orden_venta=ordenVenta,
                    id_producto_id=p["id_producto"],
                    cantidad=p["cantidad"]
                )

            # Armar respuesta con la orden actualizada
            orden_data = {
                "id_orden_venta": ordenVenta.id_orden_venta,
                "prioridad": ordenVenta.id_prioridad.descripcion,
                "fecha_entrega": ordenVenta.fecha_entrega,
                "cliente": {
                    "id": ordenVenta.id_cliente.id_cliente,
                    "nombre": ordenVenta.id_cliente.nombre
                },
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

            return JsonResponse(orden_data, status=200, safe=False)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405)


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
