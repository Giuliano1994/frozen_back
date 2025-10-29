import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .utils import buscar_empleado_por_vector_facial , registrar_fichada, obtener_info_empleado
from empleados.models import Empleado , Fichada , FaceID
from .dtos import LoginResponseDTO , FichajeResponseDTO
from ventas.models import Cliente


@csrf_exempt
def fichar_empleado_por_rostro(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    data = json.loads(request.body)
    vector = data.get("vector")
    if not vector:
        return JsonResponse({"error": "Vector facial es requerido"}, status=400)

    empleado = buscar_empleado_por_vector_facial(vector)
    if not empleado:
        return JsonResponse({"error": "Empleado no reconocido"}, status=404)

    tipo, timestamp = registrar_fichada(empleado)
    empleado_info = obtener_info_empleado(empleado)

    dto = FichajeResponseDTO(
        success=True,
        message=f"Fichaje de {tipo} registrado exitosamente",
        empleadoInfo=empleado_info
    )

    return JsonResponse(dto.to_dict())

@csrf_exempt
def login(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    data = json.loads(request.body)
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return JsonResponse({"error": "Usuario y contraseña requeridos"}, status=400)

    try:
        empleado = Empleado.objects.select_related("id_rol", "id_face").get(
            usuario=username, contrasena=password
        )
    except Empleado.DoesNotExist:
        return JsonResponse({"error": "Credenciales inválidas"}, status=401)

    dto = LoginResponseDTO(
        id_empleado=empleado.id_empleado,
        nombre=empleado.nombre,
        apellido=empleado.apellido,
        rol=empleado.id_rol.descripcion,
        vector=empleado.id_face.vector,
    )

    return JsonResponse(dto.to_dict())


@csrf_exempt
def login_ecommerce(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    data = json.loads(request.body)
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return JsonResponse({"error": "email y contraseña requeridos"}, status=400)

    try:
        cliente = Cliente.objects.get(
            email=email, contraseña=password
        )
    except Cliente.DoesNotExist:
        return JsonResponse({"error": "Credenciales inválidas"}, status=401)
    

    clienteEncontrado = {
        "nombre": cliente.nombre,
        "apellido": cliente.apellido,
        "email": cliente.email,
        "cuil": cliente.cuil,
    }

    return JsonResponse(clienteEncontrado, status = 200)