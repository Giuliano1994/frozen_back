class EmpleadoDTO:
    def __init__(self, id, usuario, nombre, apellido, rol, turno):
        self.id = id
        self.usuario = usuario
        self.nombre = nombre
        self.apellido = apellido
        self.rol = rol
        self.turno = turno

    def to_dict(self):
        return {
            "id": self.id,
            "usuario": self.usuario,
            "nombre": self.nombre,
            "apellido": self.apellido,
            "rol": self.rol,
            "turno": self.turno
        }


class RolDTO:
    def __init__(self, id_rol, descripcion):
        self.id_rol = id_rol
        self.descripcion = descripcion

    def to_dict(self):
        return {
            "id_rol": self.id_rol,
            "descripcion": self.descripcion
        }
    
class CrearEmpleadoDTO:
    def __init__(self, usuario, contrasena, nombre, apellido, id_rol, id_departamento, id_turno, vector=None):
        self.usuario = usuario
        self.contrasena = contrasena
        self.nombre = nombre
        self.apellido = apellido
        self.id_rol = id_rol
        self.id_departamento = id_departamento
        self.id_turno = id_turno
        self.vector = vector or []

        self.validar()

    def validar(self):
        if not self.usuario or len(self.usuario) < 3:
            raise ValueError("El usuario debe tener al menos 3 caracteres")
        if not self.contrasena or len(self.contrasena) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if not self.nombre:
            raise ValueError("El nombre es obligatorio")
        if not self.apellido:
            raise ValueError("El apellido es obligatorio")
        if not self.id_rol:
            raise ValueError("El id del rol es obligatorio")
        if not self.id_departamento:
            raise ValueError("El id del departamento es obligatorio")
        if not self.id_turno:
            raise ValueError("El id del turno es obligatorio")
        if not isinstance(self.vector, list):
            raise ValueError("El vector debe ser una lista")