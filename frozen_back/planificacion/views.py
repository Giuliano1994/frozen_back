from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from planificacion.planner_service import ejecutar_planificador, replanificar_produccion
from planificacion.planificador import ejecutar_planificacion_diaria_mrp
import traceback
from datetime import timedelta, date, datetime
from django.utils import timezone

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