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
from produccion.models import CalendarioProduccion
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import F, Case, When, Value, CharField, Sum
from django.utils import timezone
from datetime import timedelta, datetime
from planificacion.replanificador import replanificar_ops_por_capacidad

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
    
@api_view(['POST'])
def replanificar_capacidad_view(request):
    """
    Endpoint dedicado para disparar la Replanificación por Capacidad
    (se recomienda ejecutar inmediatamente después de cambiar 'cant_por_hora').
    
    Acepta un JSON con:
    {
        "fecha": "YYYY-MM-DD" (Opcional, simula la fecha de hoy), 
        "productos": [1, 2] // Opcional, lista de IDs de producto a replanificar
    }
    """
    
    fecha_a_usar = None
    fecha_enviada = request.data.get('fecha')
    productos_ids = request.data.get('productos')

    # --- 1. Determinar Fecha de Ejecución ---
    if fecha_enviada:
        try:
            fecha_a_usar = datetime.strptime(fecha_enviada, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"status": "error", "message": "Formato de fecha inválido. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        fecha_a_usar = timezone.localdate()

    print(f"Iniciando Replanificación de Capacidad para fecha: {fecha_a_usar}")
    
    # --- 2. Ejecutar Replanificación ---
    try:
        replanificar_ops_por_capacidad(
            fecha_simulada=fecha_a_usar,
            productos_a_replanificar_ids=productos_ids
        )
        
        mensaje = f"Replanificación por capacidad ejecutada para {fecha_a_usar}."
        if productos_ids:
            mensaje += f" Productos enfocados: {productos_ids}."
            
        return Response(
            {"status": "ok", "message": mensaje },
            status=status.HTTP_200_OK
        )
            
    except Exception as e:
        print(f"ERROR CRÍTICO al ejecutar replanificación de capacidad: {e}")
        traceback.print_exc()
        return Response(
            {"status": "error", "message": f"Error en la replanificación de capacidad: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

class CalendarioPlanificacionView(APIView):
    """
    API para obtener un feed de eventos de planificación (OPs, OCs y OVs) para un calendario.
    
    MODIFICADO:
    - La sección "Produccion" ahora lee directamente de 'CalendarioProduccion'
      para mostrar las reservas de horas reales en cada línea.
    - Añadida comprobación de seguridad para evitar errores si 'linea' o 'op' son None.
    """
    def get(self, request):
        
        eventos = []

        try:
            # ===================================================================
            # --- A. EVENTOS DE PRODUCCIÓN (¡MODIFICADO!) ---
            # (Leemos desde 'CalendarioProduccion' para OPs activas)
            # ===================================================================
            
            # Estados de OP que queremos mostrar en el calendario
            estados_op_visibles = ['En espera', 'Pendiente de inicio', 'En proceso', 'Planificada']
            
            tareas_calendario = CalendarioProduccion.objects.filter(
                id_orden_produccion__id_estado_orden_produccion__descripcion__in=estados_op_visibles
            ).select_related(
                'id_orden_produccion__id_producto', 
                'id_orden_produccion__id_estado_orden_produccion',
                'id_linea_produccion'
            )
            
            for cal_task in tareas_calendario:
                op = cal_task.id_orden_produccion
                linea = cal_task.id_linea_produccion
                
                # --- ❗️ INICIO DE CORRECCIÓN ---
                # Chequeo de seguridad: si la OP, la línea, o el producto
                # fueron borrados (y la FK se puso a NULL), saltamos esta entrada.
                if not op or not linea or not op.id_producto:
                    print(f"Omitiendo tarea de calendario {cal_task.id} por datos faltantes (OP o Línea es None)")
                    continue
                # --- ❗️ FIN DE CORRECCIÓN ---
                
                # Convertimos el DateField (fecha) a un DateTimeField (fecha + hora)
                # Asumimos que el trabajo empieza a las 00:00 (o puedes poner 8:00)
                start_dt_naive = datetime.combine(cal_task.fecha, datetime.min.time())
                start_dt = timezone.make_aware(start_dt_naive)
                
                # El fin es la hora de inicio + las horas reservadas
                end_dt = start_dt + timedelta(hours=float(cal_task.horas_reservadas))
                
                eventos.append({
                    # ID único de la tarea del calendario
                    "id": f"CAL-{cal_task.id}", 
                    # ID de Recurso (para calendarios tipo 'scheduler' que agrupan por línea)
                    #"resourceId": f"L-{linea.id_linea_produccion}", 
                    "title": f"OP-{op.id_orden_produccion}: {op.id_producto.nombre} ({int(cal_task.cantidad_a_producir)} u.)",
                    "start": start_dt.isoformat(),
                    "type": "Produccion",
                    "status": op.id_estado_orden_produccion.descripcion,
                    "linea": linea.descripcion, # Esta línea ahora es segura
                    "horas_reservadas": cal_task.horas_reservadas,
                    "cantidad_planificada_dia": cal_task.cantidad_a_producir,
                    "op_id": op.id_orden_produccion,
                    "color": "#FFC107" # Amarillo para producción
                })

            # ===================================================================
            # --- B. EVENTOS DE COMPRA (OrdenCompra - OCs) ---
            # ===================================================================
            
            ocs_pendientes = OrdenCompra.objects.filter(
                id_estado_orden_compra__descripcion='En proceso',
                fecha_entrega_estimada__isnull=False
            ).select_related('id_proveedor', 'id_estado_orden_compra')
            
            for oc in ocs_pendientes:
                
                delivery_date = oc.fecha_entrega_estimada
                
                # Convertimos DateField a Datetime (para evitar warnings 'naive')
                if isinstance(delivery_date, date) and not isinstance(delivery_date, datetime):
                     start_dt_naive = datetime.combine(delivery_date, datetime.min.time())
                     start_dt = timezone.make_aware(start_dt_naive)
                # Si ya es un DateTimeField (aware o naive), lo usamos
                elif isinstance(delivery_date, datetime):
                    if timezone.is_naive(delivery_date):
                        start_dt = timezone.make_aware(delivery_date)
                    else:
                        start_dt = delivery_date
                else:
                    continue # Omitir si no es un formato de fecha válido

                
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
                
            # ===================================================================
            # --- C. EVENTOS DE VENTA (OrdenVenta - OVs - Fechas de Entrega) ---
            # ===================================================================
            
            ovs_pendientes = OrdenVenta.objects.filter(
                id_estado_venta__descripcion__in=['Creada', 'En Preparación', 'Pendiente de Pago', 'Pendiente de Entrega'],
                fecha_entrega__isnull=False
            ).select_related('id_cliente', 'id_estado_venta')

            for ov in ovs_pendientes:
                start_dt = ov.fecha_entrega # fecha_entrega ya debería ser un DateTimeField aware
                
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt)
                
                total_productos = ov.ordenventaproducto_set.aggregate(total=Sum('cantidad'))['total'] or 0
                
                eventos.append({
                    "id": f"OV-{ov.id_orden_venta}",
                    "title": f"OV-{ov.id_orden_venta}: Entrega {ov.id_cliente.nombre} ({int(total_productos)} u.)",
                    "start": start_dt.isoformat(),
                    "end": (start_dt + timedelta(hours=1)).isoformat(), 
                    "type": "Venta (Fecha Estimada)",
                    "status": ov.id_estado_venta.descripcion,
                    "cliente": ov.id_cliente.nombre,
                    "cantidad_total": total_productos,
                    "color": "#28A745" # Verde para ventas/entregas
                })
                
            return Response(eventos, status=status.HTTP_200_OK)

        except Exception as e:
            # Imprime el error en la consola del servidor
            print(f"Error en CalendarioPlanificacionView: {e}")
            traceback.print_exc()
            # Devuelve una respuesta de error 500
            return Response(
                {"error": "Ocurrió un error interno al generar el calendario.", "detalle": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )