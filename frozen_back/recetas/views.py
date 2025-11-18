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
    Producto + Línea (sin necesitar el ID primario de la relación).
    """
    def post(self, request):
        id_producto = request.data.get("id_producto")
        id_linea = request.data.get("id_linea_produccion")
        
        # Valores a actualizar
        nueva_cant = request.data.get("cant_por_hora")
        nueva_minima = request.data.get("cantidad_minima")

        if not id_producto or not id_linea:
            return Response(
                {"error": "Debe enviar 'id_producto' y 'id_linea_produccion'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Buscar la relación existente
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

        # Actualizar solo si se enviaron los datos
        if nueva_cant is not None:
            relacion.cant_por_hora = nueva_cant
        
        if nueva_minima is not None:
            relacion.cantidad_minima = nueva_minima
            
        relacion.save()

        # Devolver el objeto actualizado
        serializer = ProductoLineaSerializer(relacion)
        return Response(serializer.data, status=status.HTTP_200_OK)