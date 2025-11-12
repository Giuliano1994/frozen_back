
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
 #   path('api/', include('empleados.urls')),
    path('api/', include('login.urls')),
    path('api/ventas/', include('ventas.urls')),
    path('api/productos/', include('productos.urls')),
    path('api/empleados/', include('empleados.urls')),
    path('api/produccion/', include('produccion.urls')),
    path('api/stock/', include('stock.urls')),
    path('api/recetas/', include('recetas.urls')),
    path('api/materias_primas/', include('materias_primas.urls')),
    path('api/compras/', include('compras.urls')),
    path('api/', include('trazabilidad.urls')),
    path('api/despachos/', include('despachos.urls')),
    path('api/planificacion/', include('planificacion.urls')),
    path('api/reportes/', include('reportes.urls')),


    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Interfaz de Swagger UI:
    path('api/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Interfaz de ReDoc:
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
