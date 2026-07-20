"""
Herramienta de rescate: restablece la contraseña de un usuario local.

La app no tiene flujo de "olvidé mi contraseña" (no hay servidor de email
en una instalación local), así que este script cubre ese caso desde la
terminal del propio equipo — quien puede ejecutarlo ya tiene acceso físico
a la base de datos, por lo que no introduce ninguna superficie de ataque
nueva.

Uso (desde la carpeta backend, con el .venv activado):

    python reset_password.py                # lista los usuarios
    python reset_password.py <usuario>      # pide la contraseña nueva

La contraseña se escribe oculta (no aparece en pantalla ni queda en el
historial de la terminal).
"""

import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.database import SessionLocal, init_db
from app.db.models import User


def list_users() -> None:
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
    if not users:
        print("No hay usuarios registrados todavía.")
        return
    print("Usuarios registrados:")
    for user in users:
        print(f"  - {user.username}  ({user.email})")
    print("\nUso: python reset_password.py <usuario>")


def reset(username: str) -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"ERROR: el usuario '{username}' no existe.")
            print("Ejecute sin argumentos para ver la lista de usuarios.")
            return 1

        password = getpass.getpass(f"Nueva contraseña para '{username}' (mín. 8): ")
        if len(password) < 8:
            print("ERROR: la contraseña debe tener al menos 8 caracteres.")
            return 1
        confirm = getpass.getpass("Repita la contraseña: ")
        if password != confirm:
            print("ERROR: las contraseñas no coinciden.")
            return 1

        user.hashed_password = hash_password(password)
        db.commit()

    print(f"Contraseña de '{username}' restablecida correctamente.")
    print("Ya puede iniciar sesión en el dashboard con la nueva contraseña.")
    return 0


if __name__ == "__main__":
    init_db()
    if len(sys.argv) < 2:
        list_users()
        sys.exit(0)
    sys.exit(reset(sys.argv[1]))
