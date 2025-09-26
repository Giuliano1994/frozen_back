class LoginResponseDTO:
    def __init__(self, nombre, apellido, rol):
        self.nombre = nombre
        self.apellido = apellido
        self.rol = rol

    def to_dict(self):
        return {
            "nombre": self.nombre,
            "apellido": self.apellido,
            "rol": self.rol,
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