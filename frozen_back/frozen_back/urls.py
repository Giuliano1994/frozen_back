"""
URL configuration for frozen_back project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

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

]
