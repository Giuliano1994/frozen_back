from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from produccion.models import LineaProduccion
from .models import ProductoLinea, Receta, RecetaMateriaPrima
from .serializers import RecetaSerializer, RecetaMateriaPrimaSerializer, ProductoLineaSerializer

# ------------------------------
# Receta
# ------------------------------
class RecetaViewSet(viewsets.ModelViewSet):
    queryset = Receta.objects.all()
    serializer_class = RecetaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_producto", "descripcion"]
    search_fields = ["descripcion", "id_producto__nombre"]

# ------------------------------
# RecetaMateriaPrima
# ------------------------------
class RecetaMateriaPrimaViewSet(viewsets.ModelViewSet):
    queryset = RecetaMateriaPrima.objects.all()
    serializer_class = RecetaMateriaPrimaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_receta", "id_materia_prima"]
    search_fields = ["id_materia_prima__nombre"]

class LineasProduccionPorProductoView(APIView):
    """
    Devuelve todas las líneas de producción asociadas a un producto,
    recibiendo el id_producto por JSON.
    """

    def post(self, request):
        id_producto = request.data.get("id_producto")

        if not id_producto:
            return Response(
                {"error": "Debe enviar 'id_producto' en el cuerpo del JSON."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Buscar las líneas asociadas al producto
        lineas_ids = ProductoLinea.objects.filter(
            id_producto=id_producto
        ).values_list("id_linea_produccion", flat=True)

        # Obtener las descripciones de esas líneas
        lineas = LineaProduccion.objects.filter(
            id_linea_produccion__in=lineas_ids
        ).values("id_linea_produccion", "descripcion")

        return Response(list(lineas), status=status.HTTP_200_OK)
    
class ProductoLineaViewSet(viewsets.ModelViewSet):
    queryset = ProductoLinea.objects.all()
    # Asumiendo que existe un serializer para ProductoLinea
    serializer_class = ProductoLineaSerializer  # Cambiar al serializer correcto cuando esté disponible
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id_producto", "id_linea_produccion"]
    search_fields = ["id_producto__nombre", "id_linea_produccion__descripcion"]



class LineasProduccionPorProductoView(APIView):
    """
    Devuelve la configuración de líneas para un producto.
    Incluye cant_por_hora y cantidad_minima.
    """
    def post(self, request):
        id_producto = request.data.get("id_producto")

        if not id_producto:
            return Response({"error": "Falta 'id_producto'"}, status=status.HTTP_400_BAD_REQUEST)

        # Buscamos los objetos ProductoLinea completos
        relaciones = ProductoLinea.objects.filter(id_producto=id_producto).select_related('id_linea_produccion')
        
        # Usamos el serializer para devolver toda la info (incluida la descripción de la línea y las capacidades)
        serializer = ProductoLineaSerializer(relaciones, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)


class ActualizarCapacidadLineaView(APIView):
    """
    Permite modificar cant_por_hora y cantidad_minima buscando por
    Producto + Línea.
    Valida que cantidad_minima < cant_por_hora.
    """
    def post(self, request):
        id_producto = request.data.get("id_producto")
        id_linea = request.data.get("id_linea_produccion")
        
        # Valores a actualizar (pueden ser None si no se envían)
        nueva_cant = request.data.get("cant_por_hora")
        nueva_minima = request.data.get("cantidad_minima")

        if not id_producto or not id_linea:
            return Response(
                {"error": "Debe enviar 'id_producto' y 'id_linea_produccion'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Buscar la relación existente en la BD
        try:
            relacion = ProductoLinea.objects.get(
                id_producto=id_producto, 
                id_linea_produccion=id_linea
            )
        except ProductoLinea.DoesNotExist:
            return Response(
                {"error": "No existe esa asignación de Producto a esa Línea."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Determinar los VALORES FINALES para la validación
        # Si mandaron un valor nuevo, usamos ese. Si no, usamos el que ya está en la BD.
        val_cant_final = nueva_cant if nueva_cant is not None else relacion.cant_por_hora
        val_minima_final = nueva_minima if nueva_minima is not None else relacion.cantidad_minima

        # 3. VALIDACIÓN DE LÓGICA (Mínimo < Máximo/Hora)
        # Solo validamos si ambos valores existen (no son nulos)
        if val_cant_final is not None and val_minima_final is not None:
            # Convertimos a int por seguridad, por si vienen como strings en el JSON
            if int(val_minima_final) >= int(val_cant_final):
                return Response(
                    {
                        "error": "Validación fallida: La cantidad mínima no puede ser mayor o igual a la capacidad por hora.",
                        "detalle": f"Mínimo ({val_minima_final}) >= Capacidad ({val_cant_final})"
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        # 4. Guardar cambios (Solo si pasó la validación)
        if nueva_cant is not None:
            relacion.cant_por_hora = nueva_cant
        
        if nueva_minima is not None:
            relacion.cantidad_minima = nueva_minima
            
        relacion.save()

        # Devolver el objeto actualizado
        serializer = ProductoLineaSerializer(relacion)
        return Response(serializer.data, status=status.HTTP_200_OK)