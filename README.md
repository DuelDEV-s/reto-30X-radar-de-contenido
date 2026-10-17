# 30X · Radar de contenido

Base funcional para el Reto 30X: **Python 3.12 + FastAPI + React/TypeScript + PostgreSQL**. Implementa los pasos 1 y 3 del esquema del equipo y un contrato de ingesta para el paso 2.

Para conectar fuentes reales y un proveedor IA/JEV, seguir [la guía de integración real](docs/real-setup.md). Distingue la configuración ya disponible del desarrollo que todavía falta.

**Análisis automático de perfiles disponible:** al crear una marca con redes sociales se consulta Bright Data primero y Meta/YouTube oficiales como respaldo y se genera un JSON con datos, métricas disponibles y una propuesta de identidad. Ver [configuración de Bright Data y respaldos](docs/bright-data.md). Sin credenciales se muestran los requisitos, sin inventar datos. Con observaciones ya guardadas, **Reinterpretar datos guardados** genera una propuesta específica sin nuevas consultas ni créditos de extracción.

## Arranque con Docker

Requiere Docker Desktop con el motor Linux activo y Docker Compose v2. Desde la raíz:

```bash
docker compose up --build -d
docker compose ps
```

- Interfaz: http://localhost:5173
- Swagger: http://localhost:8000/docs
- Salud y conexión a base de datos: http://localhost:8000/api/health
- PostgreSQL: `localhost:15432` (configurable con `POSTGRES_PORT`); base/usuario `radar`, contraseña local `radar_local_change_me`.

Los valores por defecto permiten arrancar sin configurar claves. Para personalizarlos, copiar `.env.example` a `.env` antes del primer arranque. Si la contraseña contiene caracteres reservados de URL, codificarlos en la URL de conexión; para este entorno local usar una contraseña alfanumérica facilita la configuración. Cambiar la contraseña en `.env` no modifica un volumen PostgreSQL ya inicializado.

Compose espera a que PostgreSQL esté listo; el backend aplica Alembic antes de iniciar y el frontend espera la salud de la API. La base usa un **volumen persistente**. `docker compose down` detiene el entorno conservando datos. `docker compose down -v` elimina definitivamente la base local. No ejecutar este último comando si necesitan conservarla.

Para levantar **solamente la base**:

```bash
docker compose up -d db
```

La base usa la imagen oficial de PostgreSQL; los Dockerfiles propios están en `backend/` y `frontend/`.

## Prueba de punta a punta en 2 minutos

1. Abrir la interfaz y elegir **Explorar demo**. Esto crea una marca y 18 piezas sintéticas, sin acceder a redes.
2. Abrir un tópico. Revisar evidencia temporal, gancho, afinidad y adaptación sugerida. Las URLs demo están deshabilitadas.
3. Filtrar por red y por ventana de observación. Exportar el informe JSON si lo necesitan.
4. Crear una marca propia: nombre, descripción, audiencia, región y tópicos; opcionalmente enlaces y descripciones públicas.
5. En **Identidad de marca**, editar definición, tópicos y personas; guardar y confirmar.
6. En **Fuentes e integración**, importar el lote JSON generado por sus compañeros. El radar usa el lote seleccionado; no mezcla fuentes demo con públicas.

## Responsabilidades y límites del prototipo

| Paso | Implementado | Punto de extensión |
| --- | --- | --- |
| 1 · Identidad | Nombre y perfiles, Bright Data configurable con Meta/YouTube de respaldo, JSON de análisis, síntesis breve, pilares con evidencia, audiencias por validar y revisión humana | `backend/app/profiles.py`: conectores y enriquecimiento; `draft_identity`: base del brief; un LLM sigue pendiente |
| 2 · Descubrimiento | Contrato v1, validación, procedencia, separación demo/público, idempotencia de lotes | Equipo del paso 2: entregar `BatchCreate` a `POST /api/brands/{id}/trend-batches` |
| 3 · Priorización | Score explicable, aceleración por vistas/día, coincidencia de tópicos, pieza principal, historial, hipótesis y adaptación | `backend/app/services.py:analyze`: ampliar evidencia o incorporar explicaciones de un modelo |

**Bright Data es el recolector principal de perfiles Instagram/YouTube**, con sus APIs oficiales como respaldo. No hay llamadas a modelos de IA. Los trabajos asíncronos se guardan en PostgreSQL; consultar su estado reutiliza el trabajo y una nueva extracción se solicita explícitamente. El resultado declara qué fuente se consultó, qué datos faltan y qué textos pueden incorporarse a la identidad. LinkedIn y TikTok aún no tienen conector. Las explicaciones del radar siguen siendo plantillas editoriales. El paso 2 continúa encargado del descubrimiento de tendencias. Tener un enlace público no implica permiso de recolección: el proveedor debe comprobar los términos de su fuente.

El prototipo responde: **“¿Qué tópicos de este lote muestran mayor aceleración observable, cuánto coinciden con mi marca y qué experimento editorial puedo hacer?”** No responde con fiabilidad cuáles son los 10 temas que más crecen en toda una plataforma. No estima saturación ni atribuye causalidad a gancho/formato. La confianza describe cantidad de evidencia, no probabilidad estadística.

Sin autenticación: entorno de equipo/local, con puertos Docker ligados a loopback. No desplegar públicamente sin aislamiento de usuarios, autenticación, límites de peticiones y endurecimiento. El esquema rechaza campos no definidos, pero el texto libre debe ser revisado por el equipo para excluir datos personales. No se almacenan autores ni comentarios.

## Desarrollo sin contenedores

Backend (PowerShell, Python 3.12):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
cd backend
# SQLite local por defecto. Para PostgreSQL local con Docker:
# $env:DATABASE_URL='postgresql+psycopg://radar:radar_local_change_me@localhost:15432/radar'
..\.venv\Scripts\alembic.exe upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend (otra terminal):

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Vite redirige `/api` al puerto 8000. En Docker lo hace Nginx, conservando la misma ruta de API. `.env` se usa para interpolación de Compose; para ejecutar Python local exportar las variables en la terminal. No se lee `.env` automáticamente.

## Comprobaciones

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\alembic.exe check
cd ../frontend
npm.cmd run build
cd ..
docker compose config --quiet
```

Los tests cubren el flujo API, identidad, aislamiento de lotes entre marcas, deduplicación, datos demo explícitos, observaciones inválidas, URLs, campos extra, normalización por tiempo, base cero y evidencia antigua. La CI comprueba además las migraciones sobre PostgreSQL 16.

## Estructura

```text
backend/app/        API, modelos, validación, reglas y fixtures
backend/migrations/ Migraciones Alembic (base, análisis, trabajos)
backend/tests/      Pruebas de contrato y cálculo
frontend/src/       Interfaz React, TypeScript y CSS adaptable
docs/               Contrato del paso 2, ejemplo y arquitectura
compose.yaml        PostgreSQL + FastAPI + React servido por Nginx
```

## Trabajo en equipo

Leer primero [el contrato del paso 2](docs/step-2-contract.md). Conservar los nombres y tipos de sus campos. Si necesitan más campos, acuerden una versión nueva en vez de modificar silenciosamente `1.0`. El lote es una fotografía completa de una consulta, no un delta: sus compañeros deben agrupar en él todas las observaciones históricas que quieran comparar. Los lotes anteriores se conservan para consulta explícita; no se fusionan automáticamente.

Tecnología y arranque siguen las guías oficiales de [FastAPI](https://fastapi.tiangolo.com/tutorial/sql-databases/), [Vite](https://vite.dev/guide/) y [orden de inicio de Docker Compose](https://docs.docker.com/compose/how-tos/startup-order/).
