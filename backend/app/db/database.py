"""
Capa de conexión a la base de datos (SQLAlchemy 2.0).

Compatible con SQLite (por defecto, cero configuración) y PostgreSQL
(cambiando DATABASE_URL en el .env). Expone:

- `engine`        : motor de conexión.
- `SessionLocal`  : fábrica de sesiones por-request.
- `Base`          : clase declarativa de la que heredan los modelos.
- `get_db()`      : dependencia FastAPI que abre/cierra sesión por petición.
- `init_db()`     : crea las tablas al arrancar (en producción usar Alembic).
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# SQLite necesita `check_same_thread=False` porque FastAPI puede atender la
# misma sesión desde distintos hilos del threadpool.
_connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,  # descarta conexiones muertas (útil en PostgreSQL)
)

if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_durability(dbapi_conn, _record) -> None:
        """
        Endurece SQLite contra cortes de energía:

        - WAL (write-ahead log): las escrituras van primero a un journal
          separado; un corte a mitad de escritura no corrompe la BD y lo
          ya confirmado se recupera al reabrir.
        - synchronous=FULL: cada commit espera al fsync del disco antes de
          confirmarse — máxima durabilidad a costa de unos ms por commit
          (irrelevante para el volumen de este bot).
        """
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base declarativa común para todos los modelos ORM."""


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión por petición, siempre cerrada al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crea todas las tablas registradas en Base. Idempotente."""
    # Importar los modelos registra sus tablas en Base.metadata.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_micro_migrations()


def _apply_micro_migrations() -> None:
    """
    Añade columnas nuevas a tablas ya existentes (create_all no altera
    tablas). Cada sentencia es idempotente: si la columna ya existe, el
    ALTER falla y se ignora. Para migraciones serias, usar Alembic.
    """
    from sqlalchemy import text

    statements = [
        "ALTER TABLE bot_configs ADD COLUMN strategy_params_json TEXT DEFAULT '{}'",
        "ALTER TABLE broker_credentials ADD COLUMN terminal_path VARCHAR(500)",
        "ALTER TABLE bot_configs ADD COLUMN max_drawdown_pct FLOAT DEFAULT 0.0",
        "ALTER TABLE bot_configs ADD COLUMN drawdown_cooldown_hours FLOAT DEFAULT 48.0",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:  # noqa: BLE001 — columna ya existente
                conn.rollback()
