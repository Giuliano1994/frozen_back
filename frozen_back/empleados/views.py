from django.shortcuts import render

from django.http import JsonResponse
from .models import Empleado, Rol
from .dtos import EmpleadoDTO , RolDTO

def lista_empleados(request):
    empleados = Empleado.objects.select_related("id_rol", "id_turno").all()

    data = [
        EmpleadoDTO(
            id=e.id_empleado,
            usuario=e.usuario,
            nombre=e.nombre,
            apellido=e.apellido,
            rol=e.id_rol.descripcion,
            turno=e.id_turno.descripcion
        ).to_dict()
        for e in empleados
    ]

    return JsonResponse(data, safe=False)


def menu_rol(request, nombreRol):
    rol = Rol.objects.filter(descripcion=nombreRol).first()
    if not rol:
        return JsonResponse({"error": "Rol no encontrado"}, status=404)

    dto = RolDTO(id_rol=rol.id_rol, descripcion=rol.descripcion)
    return JsonResponse({"success": True, "rol": dto.to_dict()})

