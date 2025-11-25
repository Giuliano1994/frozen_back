from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.views import APIView
from rest_framework.response import Response


# Asegúrate de que estas importaciones apunten a los servicios que corregimos
from .services import get_traceability_for_order, get_traceability_forward, get_traceability_backward_op 
from produccion.models import OrdenProduccion, OrdenProduccionPegging
from stock.models import ReservaMateriaPrima
from stock.models import ReservaStock, LoteProduccion, LoteProduccionMateria
from ventas.models import OrdenVenta, OrdenVentaProducto
from ventas.serializers import OrdenVentaSerializer
from trazabilidad.models import Configuracion
from stock.services import _enviar_telegram_async

# Asumo que esta clase está en views.py de tu app de trazabilidad
class TrazabilidadViewSet(viewsets.ViewSet):
    """
    ViewSet para realizar consultas de trazabilidad usando los servicios corregidos.
    """

    # 1. Trazabilidad Hacia Atrás (Por Orden de Venta Completa) - Método Preferido
    # GET /api/trazabilidad/orden-venta/<id_ov>/backward/
    @action(detail=True, methods=['get'], url_path='backward')
    def trace_backward_by_order(self, request, pk=None):
        """
        Trazabilidad hacia atrás para una orden de venta COMPLETA (OV -> Lote PT -> Lote MP).
        Usa el PK (ID de OrdenVenta) en la URL.
        """
        if not pk:
            return Response(
                {"error": "El ID de la Orden de Venta (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            report = get_traceability_for_order(int(pk))
        except ValueError:
            return Response(
                {"error": "ID de Orden de Venta no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)

    # 2. Trazabilidad Hacia Adelante (Por Lote de Materia Prima)
    # GET /api/trazabilidad/mp-lote/<id_lote_mp>/forward/
    # NOTA: Este método debe ser un ViewSet separado o un @action(detail=False) 
    #       si no quieres usar el router principal, pero lo dejaremos como acción simple aquí.
    @action(detail=False, methods=['get'], url_path='hacia-adelante')
    def trace_forward_by_mp_lote(self, request):
        """
        Trazabilidad hacia adelante (Lote MP -> Lote PT -> Clientes).
        Requiere: ?id_lote_mp=<id_lote_materia_prima>
        """
        id_lote_mp = request.query_params.get('id_lote_mp')
        if not id_lote_mp:
            return Response(
                {"error": "Debe proporcionar el parámetro 'id_lote_mp' (ID de LoteMateriaPrima)"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            report = get_traceability_forward(int(id_lote_mp))
        except ValueError:
            return Response(
                {"error": "ID de Lote de Materia Prima no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
            
        return Response(report, status=status.HTTP_200_OK)
    
    # 3. Trazabilidad Interna (Por Orden de Producción)
    # GET /api/trazabilidad/op/<id_op>/audit/
    @action(detail=True, methods=['get'], url_path='audit')
    def trace_op_audit(self, request, pk=None):
        """
        Auditoría interna de una Orden de Producción (OP -> OT -> No Conformidades).
        Usa el PK (ID de OrdenProduccion) en la URL.
        """
        if not pk:
            return Response(
                {"error": "El ID de la Orden de Producción (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # Usamos la función auxiliar que creamos antes
            report = get_traceability_backward_op(int(pk)) 
        except ValueError:
             return Response(
                {"error": "ID de Orden de Producción no válido."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if 'error' in report:
            return Response(report, status=status.HTTP_404_NOT_FOUND)
        
        return Response(report, status=status.HTTP_200_OK)

    # 4. Obtener Órdenes de Venta (Endpoint para auditar el destino de un Lote PT)
    # GET /api/trazabilidad/lotes-pt/<id_lote_pt>/ordenes-venta/
    # NOTA: Este método necesita un ViewSet diferente (e.g., LoteProduccionViewSet) 
    #       para usar el router, pero lo dejamos aquí con un nombre más genérico.
    @action(detail=True, methods=['get'], url_path='ordenes-venta-asociadas')
    def obtener_ordenes_venta_por_lote(self, request, pk=None):
        """
        Obtiene todas las órdenes de venta que recibieron unidades de un Lote de Producción (pk).
        """
        if not pk:
            return Response(
                {"error": "El ID de Lote de Producción (pk) es requerido en la URL."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            # Reutilizamos tu lógica original, renombrada para mayor claridad
            lote_id = int(pk)
            # Paso 1: obtener reservas asociadas al lote
            reservas = ReservaStock.objects.filter(id_lote_produccion_id=lote_id)

            if not reservas.exists():
                return Response({"message": f"No se encontraron reservas para el lote {lote_id}."},
                                status=status.HTTP_404_NOT_FOUND)

            # Paso 2 y 3: Obtener IDs únicos de OrdenVenta a través de OrdenVentaProducto
            ids_orden_venta = OrdenVentaProducto.objects.filter(
                id_orden_venta_producto__in=reservas.values_list("id_orden_venta_producto_id", flat=True)
            ).values_list("id_orden_venta_id", flat=True).distinct()

            # Paso 4: traer las órdenes de venta
            ordenes = OrdenVenta.objects.filter(id_orden_venta__in=ids_orden_venta)

            serializer = OrdenVentaSerializer(ordenes, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValueError:
             return Response({"error": "ID de Lote de Producción no válido."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


@require_http_methods(["GET"])
def ordenes_por_lote_mp(request, id_lote):
    try:
        # 1. Obtener IDs desde la reserva
        reservas = ReservaMateriaPrima.objects.filter(id_lote_materia_prima=id_lote)
        
        if not reservas.exists():
            return JsonResponse({"exito": False, "mensaje": "Lote no encontrado o sin uso"}, status=404)

        ids_ordenes = reservas.values_list('id_orden_produccion', flat=True)

        # 2. Consultar las órdenes TRAYENDO los datos relacionados
        # select_related hace un JOIN SQL automático con las tablas Producto y Estado
        ordenes = OrdenProduccion.objects.filter(
            id_orden_produccion__in=ids_ordenes
        ).select_related('id_producto', 'id_estado_orden_produccion')

        # 3. Construir la lista manualmente para que quede bonita y clara
        lista_ordenes = []
        for orden in ordenes:
            print()

            lista_ordenes.append({
                "id_orden": orden.id_orden_produccion,
                "fecha_creacion": orden.fecha_creacion,
                "cantidad_a_producir": orden.cantidad,
                "fecha_planificada": orden.fecha_planificada,
                "lote_producto": orden.id_lote_produccion_id,
            
                # AQUÍ ACCEDEMOS A LOS DATOS DE LAS OTRAS TABLAS
                "producto": orden.id_producto.nombre,
                "estado": orden.id_estado_orden_produccion.descripcion
            })

        # 4. Respuesta Final
        data = {
            "exito": True,
            "lote_consultado": id_lote,
            "total_ordenes": len(lista_ordenes),
            "resultados": lista_ordenes
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)
    
@require_http_methods(["GET"])
def obtener_lotes_produccion_por_mp(request, id_lote_mp):
    try:
        # --- PASO 1: Buscar reservas (Igual que antes) ---
        reservas = ReservaMateriaPrima.objects.filter(id_lote_materia_prima=id_lote_mp)
        
        if not reservas.exists():
            return JsonResponse({"exito": False, "mensaje": "Lote MP no encontrado o sin uso"}, status=404)

        ids_ordenes = reservas.values_list('id_orden_produccion', flat=True)

        # --- PASO 2: Buscar IDs de Lotes Finales (Igual que antes) ---
        ordenes_con_lote = OrdenProduccion.objects.filter(
            id_orden_produccion__in=ids_ordenes,
            id_lote_produccion__isnull=False 
        )
        ids_lotes_finales = ordenes_con_lote.values_list('id_lote_produccion_id', flat=True)

        if not ids_lotes_finales:
            return JsonResponse({"exito": True, "mensaje": "Sin lotes finales aún", "lotes_produccion": []})

        # --- PASO 3: Consultar Lotes + PRODUCTO ---
        # AGREGAMOS .select_related('id_producto')
        lotes = LoteProduccion.objects.filter(
            id_lote_produccion__in=ids_lotes_finales
        ).select_related('id_producto')

        # --- PASO 4: Construir respuesta con el Nombre ---
        lista_resultados = []
        for lote in lotes:
            lista_resultados.append({
                "id_lote_produccion": lote.id_lote_produccion,
                "fecha_produccion": lote.fecha_produccion,
                "cantidad": lote.cantidad,
                
                # AQUÍ ESTÁ EL CAMBIO:
                # Accedemos al objeto relacionado para sacar el nombre
                "id_producto": lote.id_producto.id_producto, 
                "producto_nombre": lote.id_producto.nombre  
            })

        return JsonResponse({
            "exito": True,
            "lote_materia_prima_origen": id_lote_mp,
            "cantidad_encontrada": len(lista_resultados),
            "lotes_produccion": lista_resultados
        })

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)
    
def obtener_ordenes_venta_por_lote(request, id_lote):
    try:
        lista_ventas = []

        # ---------------------------------------------------------
        # RUTA A: BUSCAR EN RESERVA DE STOCK (Ya fabricado y guardado)
        # ---------------------------------------------------------
        reservas_stock = ReservaStock.objects.filter(
            id_lote_produccion=id_lote
        ).select_related(
            'id_orden_venta_producto',
            'id_orden_venta_producto__id_orden_venta',
            'id_orden_venta_producto__id_orden_venta__id_cliente'
        )

        for res in reservas_stock:
            ov = res.id_orden_venta_producto.id_orden_venta
            cliente = ov.id_cliente
            
            lista_ventas.append({
                "origen_asignacion": "STOCK (Deposito)",
                "id_orden_venta": ov.id_orden_venta,
                "cliente": cliente.nombre,
                "fecha_entrega": ov.fecha_entrega,
                "producto": res.id_orden_venta_producto.id_producto.nombre,
                "cantidad_asignada": res.cantidad_reservada
            })

        # ---------------------------------------------------------
        # RUTA B: BUSCAR EN PEGGING (Asignado durante la producción)
        # ---------------------------------------------------------
        # 1. Buscamos qué Orden de Producción fabricó este lote
        ordenes_prod = OrdenProduccion.objects.filter(id_lote_produccion=id_lote)
        ids_ops = ordenes_prod.values_list('id_orden_produccion', flat=True)

        if ids_ops:
            peggings = OrdenProduccionPegging.objects.filter(
                id_orden_produccion__in=ids_ops
            ).select_related(
                'id_orden_venta_producto',
                'id_orden_venta_producto__id_orden_venta',
                'id_orden_venta_producto__id_orden_venta__id_cliente'
            )

            for peg in peggings:
                ov = peg.id_orden_venta_producto.id_orden_venta
                cliente = ov.id_cliente

                lista_ventas.append({
                    "origen_asignacion": "PEGGING (Desde Producción)",
                    "id_orden_venta": ov.id_orden_venta,
                    "cliente": cliente.nombre,
                    "fecha_entrega": ov.fecha_entrega,
                    "producto": peg.id_orden_venta_producto.id_producto.nombre,
                    "cantidad_asignada": peg.cantidad_asignada
                })

        # ---------------------------------------------------------
        # RESPUESTA FINAL
        # ---------------------------------------------------------
        if not lista_ventas:
            return JsonResponse({
                "exito": True,
                "mensaje": "El lote existe pero está LIBRE (No asignado a ninguna venta ni en stock ni en producción).",
                "ordenes_venta": []
            })

        return JsonResponse({
            "exito": True,
            "lote_produccion_consultado": id_lote,
            "cantidad_ordenes_vinculadas": len(lista_ventas),
            "ordenes_venta": lista_ventas
        })

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)


@require_http_methods(["GET"])
def obtener_materias_primas_por_lote_pt(request, id_lote_pt):
    try:
        # PASO 1: Encontrar la Orden de Producción que fabricó este lote
        ordenes = OrdenProduccion.objects.filter(id_lote_produccion=id_lote_pt)
        
        if not ordenes.exists():
            return JsonResponse({
                "exito": False, 
                "mensaje": "No se encontró una Orden de Producción origen para este lote (o el lote no existe)."
            }, status=404)

        # Obtenemos los IDs de las órdenes (generalmente es 1, pero prevenimos errores si hay más)
        ids_ordenes = ordenes.values_list('id_orden_produccion', flat=True)

        # PASO 2: Buscar en las Reservas de Materia Prima asociadas a esa orden
        # Usamos select_related para traer TODA la info en una sola consulta rápida:
        # Reserva -> LoteMP -> MateriaPrima (Nombre)
        reservas = ReservaMateriaPrima.objects.filter(
            id_orden_produccion__in=ids_ordenes
        ).select_related(
            'id_lote_materia_prima',
            'id_lote_materia_prima__id_materia_prima'
        )

        if not reservas.exists():
            return JsonResponse({
                "exito": True, 
                "mensaje": "Se encontró la orden de producción, pero no tiene materias primas reservadas (¿Error de carga?).",
                "materias_primas_utilizadas": []
            })

        # PASO 3: Construir la lista de resultados
        lista_mp = []
        for res in reservas:
            lote_mp = res.id_lote_materia_prima
            materia = lote_mp.id_materia_prima
            
            lista_mp.append({
                "materia_prima": materia.nombre,
                "id_lote_mp": lote_mp.id_lote_materia_prima,
                "fecha_vencimiento_mp": lote_mp.fecha_vencimiento,
                "cantidad_usada_en_esta_orden": res.cantidad_reservada,
                # Opcional: Para saber de qué orden vino
                "id_orden_produccion_origen": res.id_orden_produccion_id 
            })

        return JsonResponse({
            "exito": True,
            "lote_producto_terminado": id_lote_pt,
            "cantidad_ingredientes": len(lista_mp),
            "materias_primas_utilizadas": lista_mp
        })

    except Exception as e:
        return JsonResponse({"exito": False, "error": str(e)}, status=500)
    
# CONFIGURACIONES
def get_config(clave: str, default_val: int) -> int:
    """
    Busca una configuración en la BD. Si no existe, devuelve el default.
    Convierte el string de la BD a entero.
    """
    try:
        config = Configuracion.objects.get(nombre_clave=clave)
        # Convertimos a int porque en la BD se guarda como CharField (texto)
        return int(config.valor) 
    except (Configuracion.DoesNotExist, ValueError):
        # Si no existe la clave o el valor no es un número, usamos el default
        # Opcional: Podrías crear el registro automáticamente aquí si no existe
        return default_val
    





# from tu_app.utils import _enviar_telegram_async 

class NotificarRiesgoLoteView(APIView):
    def post(self, request):
        # 1. Recibimos los datos del Body
        ids_ordenes = request.data.get('ids_ordenes', [])
        nombre_producto = request.data.get('nombre_producto') # <--- Dato que viene del front

        # 2. Validaciones
        if not ids_ordenes or not isinstance(ids_ordenes, list):
            return Response(
                {"error": "Se requiere una lista de IDs en 'ids_ordenes'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not nombre_producto:
            return Response(
                {"error": "Se requiere el campo 'nombre_producto'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Buscar solo las órdenes y clientes (Consulta optimizada y simple)
        ordenes = OrdenVenta.objects.filter(pk__in=ids_ordenes).select_related('id_cliente')

        enviados = 0
        no_encontrados = len(ids_ordenes) - ordenes.count()

        for orden in ordenes:
            if not orden.id_cliente:
                continue

            # Formateamos nombre del cliente
            nombre_cliente = f"{orden.id_cliente.nombre} {orden.id_cliente.apellido}".strip()

            # 4. Construimos el mensaje usando el nombre_producto que nos enviaste
            mensaje = (
                f"🚨 *AVISO DE PREVENCIÓN - Orden #{orden.pk}*\n\n"
                f"Hola {nombre_cliente}, ¿cómo estás?\n\n"
                f"Te contacto porque detectamos que uno de los lotes de: *{nombre_producto}* "
                "que adquiriste podría estar en mal estado. "
                "Queremos ser transparentes: existe riesgo de que el tuyo sea parte de ese lote.\n\n"
                "Por prevención, te pedimos que no lo uses hasta revisarlo. Nos estaremos comunicando cuanto antes.\n\n"
                "Disculpas por el inconveniente — estamos revisando el origen para que no vuelva a ocurrir."
            )

            try:
                _enviar_telegram_async(mensaje)
                enviados += 1
            except Exception as e:
                print(f"Error enviando alerta a orden {orden.pk}: {e}")

        return Response({
            "mensaje": "Proceso finalizado",
            "alertas_enviadas": enviados,
            "ordenes_no_encontradas": no_encontrados
        }, status=status.HTTP_200_OK)