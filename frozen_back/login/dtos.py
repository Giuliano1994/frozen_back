class LoginResponseDTO:
    def __init__(self, nombre, apellido, rol, vector, id_empleado):
        self.id_empleado = id_empleado
        self.nombre = nombre
        self.apellido = apellido
        self.rol = rol
        self.vector = vector

    def to_dict(self):
        return {
            "id_empleado": self.id_empleado,
            "nombre": self.nombre,
            "apellido": self.apellido,
            "rol": self.rol,
            "vector": self.vector,
        }


class FichajeResponseDTO:
    def __init__(self, success, message, empleadoInfo):
        self.success = success
        self.message = message
        self.empleadoInfo = empleadoInfo  # Diccionario con info del empleado

    def to_dict(self):
        return {
            "success": self.success,
            "message": self.message,
            "empleadoInfo": self.empleadoInfo
        }
