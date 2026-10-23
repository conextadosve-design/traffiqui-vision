"""Traffiqui Vision.

En el programa instalado este paquete y `cloud/` van aparte del ejecutable, en {programa}\\codigo: una
actualización solo cambia esa carpeta (pocos MB). BASE_REQUIRED es la versión de la base (Python, librerías
y modelos, ver packaging/BASE_VERSION) que necesita este código; si una actualización añade una librería,
sube los dos números y hay que reinstalar con el instalador completo.
"""
BASE_REQUIRED = "1"
