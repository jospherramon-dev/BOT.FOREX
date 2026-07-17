# BOT.FOREX — Bot de Trading de Forex Automatizado

Sistema profesional y modular de trading algorítmico para Forex, con motor de
ejecución, gestión de riesgo, backtesting integrado, notificaciones por
Telegram y un Dashboard de control estilo *trading terminal* (dark theme).

---

## 1. Estructura del Proyecto

```
BOT.FOREX/
├── README.md
├── .gitignore
├── docs/
│   └── ARCHITECTURE.md              # Arquitectura y flujo de comunicación
│
├── backend/                         # ── PYTHON / FastAPI ──
│   ├── requirements.txt
│   ├── .env.example                 # Plantilla de variables de entorno
│   ├── data/
│   │   └── historical/              # CSVs de datos históricos (backtesting)
│   ├── tests/                       # Tests unitarios (pytest)
│   └── app/
│       ├── main.py                  # Punto de entrada FastAPI (ASGI)
│       │
│       ├── core/                    # Núcleo transversal
│       │   ├── config.py            # Configuración (pydantic-settings)
│       │   ├── security.py          # JWT, hashing bcrypt, cifrado Fernet
│       │   └── logger.py            # Logging estructurado + buffer en vivo
│       │
│       ├── db/                      # Capa de persistencia (SQLAlchemy)
│       │   ├── database.py          # Engine, sesiones, Base declarativa
│       │   └── models.py            # Modelos ORM (usuarios, trades, etc.)
│       │
│       ├── schemas/                 # Contratos de la API (Pydantic)
│       │   ├── auth.py
│       │   ├── broker.py
│       │   └── trading.py
│       │
│       ├── api/                     # Capa HTTP REST
│       │   ├── deps.py              # Dependencias (DB session, usuario JWT)
│       │   └── routes/
│       │       ├── auth.py          # Módulo A: login / registro / JWT
│       │       ├── broker.py        # Módulo A: credenciales cifradas + test
│       │       └── assets.py        # Módulo A: selector de pares (watchlist)
│       │
│       ├── brokers/                 # Conectores de broker (patrón Adapter)
│       │   ├── base.py              # Interfaz abstracta BrokerConnector
│       │   ├── mt5_connector.py     # MetaTrader 5 (paquete oficial MT5)
│       │   ├── oanda_connector.py   # OANDA REST v20 (httpx)
│       │   └── factory.py           # Fábrica: crea el conector según config
│       │
│       ├── strategies/              # Estrategias enchufables (plugin)
│       │   ├── base_strategy.py     # Clase base + contrato Signal
│       │   └── ma_rsi_crossover.py  # Estrategia por defecto (plantilla)
│       │
│       ├── engine/                  # Módulo B: motor de trading y riesgo
│       ├── backtesting/             # Módulo C: motor de backtesting
│       └── notifications/           # Módulo D: Telegram
│
└── frontend/                        # ── REACT + Tailwind + Recharts ──
    └── (Módulo E: Dashboard — se genera en el siguiente paso)
```

## 2. Comunicación Backend ↔ Frontend

- **API REST (HTTP/JSON):** el frontend React consume `http://localhost:8000/api/v1/*`
  para todo lo transaccional: login, guardar credenciales, configurar riesgo,
  lanzar backtests, cerrar operaciones manualmente.
- **WebSocket (`/ws/live`):** canal permanente para datos en tiempo real:
  ticks de precio, balance/equity, operaciones abiertas y logs del sistema.
  El backend hace *push*; el frontend solo escucha y renderiza.
- **Autenticación:** el login devuelve un JWT que el frontend adjunta en el
  header `Authorization: Bearer <token>` de cada petición (y como query param
  en el handshake del WebSocket).
- **CORS** habilitado en FastAPI para el origen del dev-server de Vite (`:5173`).

## 3. Puesta en Marcha (Backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # editar SECRET_KEY y ENCRYPTION_KEY
uvicorn app.main:app --reload --port 8000
```

Documentación interactiva de la API: `http://localhost:8000/docs` (Swagger UI).

## 4. Seguridad

- Contraseñas de usuario: hash **bcrypt** (nunca en texto plano).
- Credenciales del broker y token de Telegram: cifrado simétrico **Fernet
  (AES-128-CBC + HMAC)** con clave dedicada `ENCRYPTION_KEY`, separada del
  secreto JWT.
- Sesiones: **JWT firmado (HS256)** con expiración configurable.

## 5. Roadmap de Módulos

| Módulo | Descripción | Estado |
|--------|-------------|--------|
| A | Autenticación, credenciales broker, selector de activos | ✅ Implementado |
| B | Motor de trading y gestión de riesgo (SL/TP, break-even, trailing, lote dinámico) | ✅ Implementado |
| C | Motor de backtesting (equity curve, drawdown, sharpe) | ✅ Implementado |
| D | Notificaciones Telegram | ⏳ Siguiente |
| E | Dashboard React (Live, Analytics, Backtest) | ⏳ Pendiente |
