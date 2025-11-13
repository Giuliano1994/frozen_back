from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from compras.models import OrdenCompra
from ventas.models import OrdenVenta
from produccion.models import OrdenProduccion
from planificacion.planner_service import ejecutar_planificador, replanificar_produccion
from planificacion.planificador import ejecutar_planificacion_diaria_mrp
import traceback
from datetime import timedelta, date, datetime
from django.utils import timezone
from produccion.models import OrdenProduccion
from compras.models import OrdenCompra
from ventas.models import OrdenVenta # Necesitas importar este modelo
from django.db import models

from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import F, Case, When, Value, CharField
from django.utils import timezone
from datetime import timedelta, datetime

@api_view(['POST']) # Define que esta vista solo acepta POST
def ejecutar_planificacion_view(request):
    """
    Endpoint para disparar el script de planificación de Google OR-Tools.
    """
    try:
        print("Iniciando planificador desde el endpoint /planificacion/...")
        
        # Llama a tu función principal del planner_service
        ejecutar_planificador() 
        
        return Response(
            {"mensaje": "Planificador ejecutado exitosamente. Se crearon las Órdenes de Trabajo."}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        print(f"Error al ejecutar el planificador desde API: {str(e)}")
        return Response(
            {"error": f"Ocurrió un error al ejecutar el planificador: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['POST']) # Define que esta vista solo acepta POST
def replanificar_produccion_view(request):
    """
    Endpoint para disparar el script de planificación de Google OR-Tools.
    """
    try:
        print("Iniciando planificador desde el endpoint /planificacion/...")
        
        # Llama a tu función principal del planner_service
        replanificar_produccion() 
        
        return Response(
            {"mensaje": "Planificador ejecutado exitosamente. Se crearon las Órdenes de Trabajo."}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        print(f"Error al ejecutar el planificador desde API: {str(e)}")
        return Response(
            {"error": f"Ocurrió un error al ejecutar el planificador: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    



@api_view(['POST'])
def ejecutar_planificador_view(request):
    """
    Endpoint para disparar manualmente el Planificador MRP Diario.
    
    Opcionalmente, acepta un JSON para simular una fecha:
    {
        "fecha": "YYYY-MM-DD"
    }
    """
    
    fecha_a_usar = None
    fecha_enviada = request.data.get('fecha')

    if fecha_enviada:
        # Si el usuario envía una fecha, la usamos para simular
        try:
            fecha_a_usar = datetime.strptime(fecha_enviada, "%Y-%m-%d").date()
            print(f"Simulando ejecución del planificador para la fecha: {fecha_a_usar}")
        except ValueError:
            return Response(
                {"status": "error", "message": "Formato de fecha inválido. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        # Si no se envía fecha, usa el día real (para producción)
        fecha_a_usar = timezone.localdate()
        print(f"Ejecutando planificador para la fecha actual: {fecha_a_usar}")

    try:
       # --- INICIO DE LÓGICA MODIFICADA ---
        
        # 1. Primero, corre el MRP para determinar QUÉ producir y CUÁNDO (Crea OPs "Pendiente de inicio")
        print("\n--- INICIANDO FASE 1: MRP (Planificación de Materiales) ---")
        ejecutar_planificacion_diaria_mrp(fecha_a_usar)
        print("--- FASE 1: MRP COMPLETADA ---")

        # 2. Segundo, corre el Scheduler para planificar el día de MAÑANA
        #    (Toma las OPs "Pendiente de inicio" para mañana y crea las OTs)
        print("\n--- INICIANDO FASE 2: SCHEDULER (Planificación de Taller) ---")
        # Nota: El scheduler usa 'timezone.localdate() + 1' internamente,
        # así que no necesita la fecha simulada (a menos que quieras cambiarlo).
        ejecutar_planificador(fecha_a_usar)
        print("--- FASE 2: SCHEDULER COMPLETADA ---")
        
        # --- FIN DE LÓGICA MODIFICADA ---
        print("Planificador MRP ejecutado exitosamente desde la API.")
        return Response(
            {"status": "ok", "message": f"Planificador MRP ejecutado para {fecha_a_usar}." },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        # Captura cualquier error que ocurra durante la planificación
        print(f"ERROR al ejecutar planificador desde API: {e}")
        traceback.print_exc() # Imprime el error completo en la consola del servidor
        return Response(
            {"status": "error", "message": f"Error al ejecutar el planificador: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
class CalendarioPlanificacionView(APIView):
    """
    API para obtener un feed de eventos de planificación (OPs, OCs y OVs) para un calendario.
    Filtra eventos por fecha de inicio/entrega.
    """
    def get(self, request):
        
        eventos = []

        # --- A. EVENTOS DE PRODUCCIÓN (OrdenProduccion - OPs) ---
        
        ops_pendientes = OrdenProduccion.objects.filter(
            id_estado_orden_produccion__descripcion__in=['En espera', 'Pendiente de inicio', 'En proceso', 'Planificada']
        ).select_related('id_producto', 'id_estado_orden_produccion')
        
        for op in ops_pendientes:
            
            start_dt = op.fecha_inicio
            
            # Estimamos 8 horas de duración para la visualización
            end_dt = start_dt + timedelta(hours=8) 
            
            # Usamos fecha_planificada (que probablemente sea la fecha de fin o entrega ajustada)
            fecha_planificada_op = op.fecha_planificada if op.fecha_planificada else None

            eventos.append({
                "id": f"OP-{op.id_orden_produccion}",
                "title": f"OP-{op.id_orden_produccion}: {op.id_producto.nombre} ({op.cantidad} u.)",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "type": "Produccion",
                "status": op.id_estado_orden_produccion.descripcion,
                "quantity": op.cantidad,
                "fecha_planificada": fecha_planificada_op.isoformat() if fecha_planificada_op else None,
                "color": "#FFC107" # Amarillo para producción
            })

        # --- B. EVENTOS DE COMPRA (OrdenCompra - OCs) ---
        
        ocs_pendientes = OrdenCompra.objects.filter(
            id_estado_orden_compra__descripcion='En proceso',
            fecha_entrega_estimada__isnull=False # Debe tener una fecha estimada para mostrar
        ).select_related('id_proveedor', 'id_estado_orden_compra')
        
        for oc in ocs_pendientes:
            
            delivery_date = oc.fecha_entrega_estimada
            
            # Asumimos que la entrega ocurre a la hora de inicio laboral
            start_dt = timezone.make_aware(delivery_date) if isinstance(delivery_date, (timezone.datetime, datetime)) else timezone.make_aware(datetime.combine(delivery_date, datetime.min.time()))
            
            try:
                items_count = oc.ordencompramateriaprima_set.count() 
            except AttributeError:
                items_count = 0
                
            
            eventos.append({
                "id": f"OC-{oc.id_orden_compra}",
                "title": f"OC-{oc.id_orden_compra}: Recepción MP ({oc.id_proveedor.nombre}, {items_count} ítems)",
                "start": start_dt.isoformat(),
                "end": (start_dt + timedelta(hours=2)).isoformat(), # Asumimos 2h de recepción
                "type": "Compra (Recepción)",
                "status": oc.id_estado_orden_compra.descripcion,
                "proveedor": oc.id_proveedor.nombre,
                "color": "#17A2B8" # Azul claro para compras
            })
            
        # --- C. EVENTOS DE VENTA (OrdenVenta - OVs - Fechas de Entrega) ---
        
        # Filtramos las OVs que no están finalizadas y tienen una fecha de entrega
        ovs_pendientes = OrdenVenta.objects.filter(
            id_estado_venta__descripcion__in=['Creada', 'En Preparación', 'Pendiente de Pago', 'Pendiente de Entrega'],
            fecha_entrega__isnull=False # Usamos la fecha límite del cliente
        ).select_related('id_cliente', 'id_estado_venta')

        for ov in ovs_pendientes:
            # Usamos la fecha_entrega (límite del cliente) como el punto de inicio del evento
            start_dt = ov.fecha_entrega 
            
            # Usamos la fecha_entrega_planificada (fecha ajustada por MRP) para el título/detalle
            fecha_planificada_ov = ov.fecha_entrega_planificada if ov.fecha_entrega_planificada else None

            # Buscamos la cantidad total de productos
            total_productos = ov.ordenventaproducto_set.aggregate(total=models.Sum('cantidad'))['total'] or 0
            
            eventos.append({
                "id": f"OV-{ov.id_orden_venta}",
                "title": f"OV-{ov.id_orden_venta}: Entrega {ov.id_cliente.nombre} ({total_productos} u.)",
                # El evento empieza en la fecha límite de entrega
                "start": start_dt.isoformat(),
                # El evento dura 1 hora para visualización simple
                "end": (start_dt + timedelta(hours=1)).isoformat(), 
                "type": "Venta (Fecha Estimada)",
                "status": ov.id_estado_venta.descripcion,
                "cliente": ov.id_cliente.nombre,
                "cantidad_total": total_productos,
                "fecha_planificada_mrp": fecha_planificada_ov.isoformat() if fecha_planificada_ov else "N/A",
                "color": "#28A745" # Verde para ventas/entregas
            })
            
        return Response(eventos, status=status.HTTP_200_OK)