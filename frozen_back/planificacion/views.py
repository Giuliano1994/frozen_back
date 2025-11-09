from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from planificacion.planner_service import ejecutar_planificador, replanificar_produccion

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