import json
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import Empleado, FaceID, Rol
from .dtos import CrearEmpleadoDTO, EmpleadoDTO , RolDTO

from rest_framework import viewsets
from .models import (
    Departamento, Turno, FaceID, Rol, Empleado, Fichada,
    Permiso, RolPermiso
)

from .serializers import (
    DepartamentoSerializer, TurnoSerializer, FaceIDSerializer,
    RolSerializer, EmpleadoSerializer, FichadaSerializer,
    PermisoSerializer, RolPermisoSerializer
)

class DepartamentoViewSet(viewsets.ModelViewSet):
    queryset = Departamento.objects.all()
    serializer_class = DepartamentoSerializer


class TurnoViewSet(viewsets.ModelViewSet):
    queryset = Turno.objects.all()
    serializer_class = TurnoSerializer


class FaceIDViewSet(viewsets.ModelViewSet):
    queryset = FaceID.objects.all()
    serializer_class = FaceIDSerializer


class PermisoViewSet(viewsets.ModelViewSet):
    queryset = Permiso.objects.all()
    serializer_class = PermisoSerializer


class RolViewSet(viewsets.ModelViewSet):
    queryset = Rol.objects.all()
    serializer_class = RolSerializer


class RolPermisoViewSet(viewsets.ModelViewSet):
    queryset = RolPermiso.objects.all()
    serializer_class = RolPermisoSerializer


class EmpleadoViewSet(viewsets.ModelViewSet):
    queryset = Empleado.objects.all()
    serializer_class = EmpleadoSerializer


class FichadaViewSet(viewsets.ModelViewSet):
    queryset = Fichada.objects.all()
    serializer_class = FichadaSerializer



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


@csrf_exempt
def crear_empleado(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            dto = CrearEmpleadoDTO(
                usuario=data.get("usuario"),
                contrasena=data.get("contrasena"),
                nombre=data.get("nombre"),
                apellido=data.get("apellido"),
                id_rol=data.get("id_rol"),
                id_departamento=data.get("id_departamento"),
                id_turno=data.get("id_turno"),
                vector=data.get("vector", [])
            )

            faceid = FaceID.objects.create(vector=dto.vector)

            empleado = Empleado.objects.create(
                usuario=dto.usuario,
                contrasena=dto.contrasena,
                nombre=dto.nombre,
                apellido=dto.apellido,
                id_face_id=faceid.id_face,
                id_rol_id=dto.id_rol,
                id_departamento_id=dto.id_departamento,
                id_turno_id=dto.id_turno
            )

            return JsonResponse({"id": empleado.id_empleado, "usuario": empleado.usuario}, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Método no permitido"}, status=405)



def permisos_por_rol(request, nombreRol):
    """
    Devuelve los permisos asignados a un rol específico.
    """
    rol = Rol.objects.filter(descripcion=nombreRol).first()
    if not rol:
        return JsonResponse({"error": "Rol no encontrado"}, status=404)

    permisos = rol.permisos.all()
    permisos_list = []
    for p in permisos:
        permisos_list.append({
            "id_permiso": p.id_permiso,
            "titulo": p.titulo,
            "descripcion": p.descripcion,
            "link": p.link
        })

    return JsonResponse({
        "success": True,
        "rol": rol.descripcion,
        "permisos": permisos_list
    })