import json
from django.shortcuts import render
from rest_framework import viewsets, filters
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from django.conf import settings
from empleados.models import Empleado
from stock.models import LoteProduccion  # según tu estructura
from django.db import models
from rest_framework import status
from .services import  cancelar_orden_venta, facturar_orden_y_descontar_stock, crear_nota_credito_y_devolver_stock, registrar_orden_venta_y_actualizar_estado
from .models import Factura, OrdenVenta, Reclamo, Sugerencia, NotaCredito
from django.db import transaction
from .filters import OrdenVentaFilter
 
from .models import EstadoVenta, Cliente, OrdenVenta, OrdenVentaProducto, Prioridad
from .serializers import (
    EstadoVentaSerializer,
    ClienteSerializer,
    OrdenVentaSerializer,
    OrdenVentaProductoSerializer,
    PrioridadSerializer,
    ReclamoSerializer,
    SugerenciaSerializer,
    NotaCreditoSerializer,
    HistoricalOrdenVentaSerializer, 
    HistoricalNotaCreditoSerializer
)



from rest_framework.views import APIView
from datetime import datetime
from .services import calcular_fecha_estimada_entrega

class EstadoVentaViewSet(viewsets.ModelViewSet):
    queryset = EstadoVenta.objects.all()
    serializer_class = EstadoVentaSerializer

class ReclamoViewSet(viewsets.ModelViewSet):
    queryset = Reclamo.objects.all()
    serializer_class = ReclamoSerializer

class SugerenciaViewSet(viewsets.ModelViewSet):
    queryset = Sugerencia.objects.all()
    serializer_class = SugerenciaSerializer

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

    @action(detail=False, methods=['get'], url_path='no-pagadas-o-facturadas')
    def get_no_pagadas_o_facturadas(self, request):
        # Filtra todas las órdenes que NO tengan estado "Pagada" o "Facturada"
        ordenes = OrdenVenta.objects.filter(
            id_estado_venta=1
        )



        serializer = self.get_serializer(ordenes, many=True)
        return Response(serializer.data)


   
    @action(detail=False, methods=['delete'], url_path='bulk-delete') 
    def bulk_delete(self, request):
        """
        Borra órdenes dentro de un rango de IDs pasados como query params: ?inicio=530&fin=200
        """
        inicio = request.query_params.get('inicio')
        fin = request.query_params.get('fin')

        if not inicio or not fin:
            return Response({"detail": "Se requieren parámetros 'inicio' y 'fin'"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            inicio = int(inicio)
            fin = int(fin)
        except ValueError:
            return Response({"detail": "Los parámetros deben ser números enteros"}, status=status.HTTP_400_BAD_REQUEST)

        # Filtrar órdenes dentro del rango
        ordenes = OrdenVenta.objects.filter(id_orden_venta__lte=inicio, id_orden_venta__gte=fin)
        count = ordenes.count()
        ordenes.delete()  # borrará relaciones CASCADE automáticamente
        return Response({"detail": f"{count} órdenes borradas"}, status=status.HTTP_204_NO_CONTENT)



class OrdenVentaProductoViewSet(viewsets.ModelViewSet):
    queryset = OrdenVentaProducto.objects.all()
    serializer_class = OrdenVentaProductoSerializer
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        orden_id = response.data.get("id_orden_venta")
        orden = OrdenVenta.objects.get(pk=orden_id)
        
       # --- CAMBIO ---
        # Llamamos al nuevo servicio simple
        registrar_orden_venta_y_actualizar_estado(orden)
        # --- FIN CAMBIO ---
        
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

       # --- CAMBIO ---
        print(f"Producto eliminado de la orden #{orden.pk}. Registrando para planificador...")
        registrar_orden_venta_y_actualizar_estado(orden)
        # --- FIN CAMBIO ---

        # 4. Devolvemos una respuesta vacía, como es estándar en DELETE.
        return Response(status=status.HTTP_204_NO_CONTENT)




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
    if request.method == "PUT":
        try:
            data = json.loads(request.body)
            id_orden_venta = data.get("id_orden_venta")
            if not id_orden_venta:
                return JsonResponse({"error": "El campo 'id_orden_venta' es obligatorio"}, status=400)
            
            # --- INICIO DE VALIDACIÓN MANUAL ---
            if "tipo_venta" in data:
                tipo_venta_enviado = data.get("tipo_venta")
                validos_tipo_venta = OrdenVenta.TipoVenta.values
                if tipo_venta_enviado not in validos_tipo_venta:
                    return JsonResponse({
                        "error": f"El valor de 'tipo_venta' no es válido. Debe ser uno de: {validos_tipo_venta}"
                    }, status=400)

            if "zona" in data:
                zona_enviada = data.get("zona")
                validos_zona = OrdenVenta.TipoZona.values
                if zona_enviada and zona_enviada not in validos_zona:
                    return JsonResponse({
                        "error": f"El valor de 'zona' no es válido. Debe ser uno de: {validos_zona}"
                    }, status=400)
            # --- FIN DE VALIDACIÓN MANUAL ---

            with transaction.atomic():
                ordenVenta = OrdenVenta.objects.get(pk=id_orden_venta)
                
                # --- INICIO DE LA MODIFICACIÓN ---

                # 1. Obtenemos los IDs de los productos afectados ANTES de cualquier cambio.
                productos_afectados_antes = set(
                    OrdenVentaProducto.objects.filter(id_orden_venta=ordenVenta).values_list('id_producto_id', flat=True)
                )

                # 2. Actualizamos la cabecera de la orden
                if "fecha_entrega" in data:
                    ordenVenta.fecha_entrega = data.get("fecha_entrega")
                if "id_prioridad" in data:
                    ordenVenta.id_prioridad_id = data.get("id_prioridad")
                if "tipo_venta" in data:
                    ordenVenta.tipo_venta = data.get("tipo_venta")
                if "calle" in data:
                    ordenVenta.calle=data.get("calle"),
                if "altura" in data:
                    ordenVenta.altura=data.get("altura"),
                if "localidad" in data:
                    ordenVenta.localidad=data.get("localidad"),
                if "zona" in data:    
                    ordenVenta.zona=data.get("zona")

                ordenVenta.save()

                # 3. Eliminamos los productos antiguos (liberando sus reservas)
                OrdenVentaProducto.objects.filter(id_orden_venta=ordenVenta).delete()

                # 4. Insertamos los nuevos productos
                productos_nuevos = data.get("productos", [])
                productos_afectados_despues = set()
                for p in productos_nuevos:
                    producto_id = p["id_producto"]
                    OrdenVentaProducto.objects.create(
                        id_orden_venta=ordenVenta,
                        id_producto_id=producto_id,
                        cantidad=p["cantidad"]
                    )
                    productos_afectados_despues.add(producto_id)
                
              # --- CAMBIO ---
                # 5. Volvemos a ejecutar el servicio de gestión SIMPLE
                registrar_orden_venta_y_actualizar_estado(ordenVenta)
                

            # --- FIN DE LA MODIFICACIÓN ---

            # Armar la respuesta final
            serializer = OrdenVentaSerializer(ordenVenta)
            return JsonResponse(serializer.data, status=200)

        except OrdenVenta.DoesNotExist:
            return JsonResponse({"error": "Orden de venta no encontrada"}, status=404)
        except Exception as e:
            import traceback
            traceback.print_exc()
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
            
            # --- INICIO DE VALIDACIÓN MANUAL ---
            tipo_venta_enviado = data.get("tipo_venta")
            zona_enviada = data.get("zona")
            # 1. Validar tipo_venta
            validos_tipo_venta = OrdenVenta.TipoVenta.values
            if tipo_venta_enviado not in validos_tipo_venta:
                return JsonResponse({
                    "error": f"El valor de 'tipo_venta' no es válido. Debe ser uno de: {validos_tipo_venta}"
                }, status=400)

            # 2. Validar zona (solo si se envió)
            validos_zona = OrdenVenta.TipoZona.values
            if zona_enviada and zona_enviada not in validos_zona:
                return JsonResponse({
                    "error": f"El valor de 'zona' no es válido. Debe ser uno de: {validos_zona}"
                }, status=400)
            # --- FIN DE VALIDACIÓN MANUAL ---
            
            with transaction.atomic():
                # Validar empleado si se envió
                id_empleado = data.get("id_empleado")
                if id_empleado and not Empleado.objects.filter(pk=id_empleado).exists():
                    return JsonResponse({"error": "Empleado no encontrado"}, status=400)

                # Crear la orden de venta directamente
                orden_venta = OrdenVenta.objects.create(
                    id_cliente_id=data.get("id_cliente"),
                    id_estado_venta=estado_creada,
                    id_prioridad_id=data.get("id_prioridad"),
                    fecha_entrega=data.get("fecha_entrega"),
                    tipo_venta=data.get("tipo_venta"),
                    calle=data.get("calle"),
                    altura=data.get("altura"),
                    localidad=data.get("localidad"),
                    zona=data.get("zona"),
                    id_empleado_id=id_empleado if id_empleado else None
                )

                productos = data.get("productos", [])
                for p in productos:
                    OrdenVentaProducto.objects.create(
                        id_orden_venta=orden_venta,
                        id_producto_id=p["id_producto"],
                        cantidad=p["cantidad"]
                    )

               # --- CAMBIO ---
                # LLAMADA ÚNICA AL SERVICIO SIMPLE
                registrar_orden_venta_y_actualizar_estado(orden_venta)
                # --- FIN CAMBIO ---

            # Devolvemos la orden con su estado final y todos sus datos
            serializer = OrdenVentaSerializer(orden_venta)
            return JsonResponse(serializer.data, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    
    return JsonResponse({"error": "Método no permitido"}, status=405)


    

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



class NotaCreditoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para crear y ver Notas de Crédito.
    La creación de una NC dispara la devolución de stock.
    """
    queryset = NotaCredito.objects.all().order_by('-fecha')
    serializer_class = NotaCreditoSerializer

    def create(self, request, *args, **kwargs):
        """
        Sobre-escribe el método POST para crear una NC.
        Espera: { "id_factura": <id>, "motivo": "<texto>" }
        """
        id_factura = request.data.get('id_factura')
        motivo = request.data.get('motivo')

        if not id_factura:
            return Response({"error": "El campo 'id_factura' es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            factura = Factura.objects.get(pk=id_factura)
            orden_venta = factura.id_orden_venta
            
            # Llamamos al servicio que hace toda la magia
            nota_credito = crear_nota_credito_y_devolver_stock(orden_venta, motivo)
            
            # Devolvemos la NC creada
            serializer = self.get_serializer(nota_credito)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except (Factura.DoesNotExist, OrdenVenta.DoesNotExist):
            return Response({"error": "La factura o la orden de venta asociada no existen."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            # Captura errores del servicio (ej. "Ya existe NC", "Orden no pagada")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        



class HistorialOrdenVentaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo-lectura para ver el log global de todas las Órdenes de Venta.
    """
    queryset = OrdenVenta.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalOrdenVentaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_estado_venta', 'id_cliente']
    search_fields = ['history_user__usuario', 'id_cliente__nombre']

class HistorialNotaCreditoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo-lectura para ver el log global de todas las Notas de Crédito.
    """
    queryset = NotaCredito.history.model.objects.all().order_by('-history_date')
    serializer_class = HistoricalNotaCreditoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['history_type', 'history_user', 'id_factura']
    search_fields = ['history_user__usuario', 'motivo']









class VerificarFactibilidadVentaView(APIView):
    def post(self, request):
        """
        Recibe: { "producto_id": 1, "cantidad": 200, "fecha_solicitada": "2025-11-18" }
        Devuelve: { "posible": false, "fecha_sugerida": "2025-11-21", "mensaje": "..." }
        """
        try:
            producto_id = request.data.get('producto_id')
            cantidad = int(request.data.get('cantidad'))
            fecha_solicitada_str = request.data.get('fecha_solicitada')
            
            # Validar inputs
            if not all([producto_id, cantidad, fecha_solicitada_str]):
                 return Response({"error": "Faltan datos"}, status=status.HTTP_400_BAD_REQUEST)

            fecha_solicitada = datetime.strptime(fecha_solicitada_str, '%Y-%m-%d').date()
            
            # Llamar al servicio de cálculo
            resultado = calcular_fecha_estimada_entrega(producto_id, cantidad)
            
            if "error" in resultado:
                return Response(resultado, status=status.HTTP_400_BAD_REQUEST)
            
            fecha_calculada = resultado['fecha_estimada']
            es_factible = fecha_calculada <= fecha_solicitada
            
            response_data = {
                "es_factible": es_factible,
                "fecha_solicitada": fecha_solicitada,
                "fecha_sugerida": fecha_calculada,
                "dias_retraso": (fecha_calculada - fecha_solicitada).days if not es_factible else 0,
                "detalles": resultado.get('detalles', {}),
                "mensaje": "Stock disponible" if resultado['origen'] == "Stock Existente" else "Requiere Producción"
            }
            
            if not es_factible:
                response_data["warning"] = f"Imposible cumplir para el {fecha_solicitada}. Fecha más temprana: {fecha_calculada}"

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





    