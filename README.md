# 30X · Radar de contenido

Prototipo del Reto 30X: **Python 3.12 + FastAPI + React/TypeScript + PostgreSQL**. Conecta identidad de marca, los dos motores de descubrimiento del paso 2 y un informe editorial visual del paso 3.

Para conectar fuentes reales y un proveedor IA/JEV, seguir [la guía de integración real](docs/real-setup.md). Distingue la configuración ya disponible del desarrollo que todavía falta.

**Nuevo paso 3:** prioridades por corrida, gráficos de evolución con unidades explícitas, encaje con marca, evidencia con previews bajo demanda, propuestas, brief descargable y enlaces con filtros. Lee datos guardados sin iniciar trabajos de pago. [Flujo y metodología del informe editorial](docs/editorial-radar.md).

**Análisis automático de perfiles disponible:** al crear una marca con redes sociales se consulta Bright Data primero y Meta/YouTube oficiales como respaldo y se genera un JSON con datos, métricas disponibles y una propuesta de identidad. Ver [configuración de Bright Data y respaldos](docs/bright-data.md). Sin credenciales se muestran los requisitos, sin inventar datos. Con observaciones ya guardadas, **Reinterpretar datos guardados** genera una propuesta específica sin nuevas consultas ni créditos de extracción.

**Descubrimiento por red:** en **Descubrimiento** se elige la red. Instagram y TikTok buscan creadores por tópico (TikTok parte de una búsqueda de videos por palabra clave en Bright Data; ver [creadores de TikTok](docs/tiktok.md)); LinkedIn y YouTube (solos o combinados) ejecutan el radar de tendencias, que cruza la demanda real de YouTube con lo que se publica en LinkedIn y entrega propuestas con evidencia. Solo APIs oficiales. Ver [radar de tendencias LinkedIn + YouTube](docs/trend-radar.md).
**Relevancia de posts:** la búsqueda por tópico trae los posts de los últimos 30 días (máx. 30 por creador) de los creadores aprobados y mide cuáles rindieron por encima de su propia línea base, corrigiendo edad y formato. Ver [línea base y relevancia de posts](docs/post-relevance.md).

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

Para desarrollar el backend sin reconstruir la imagen en cada cambio, usar la capa de desarrollo; monta `backend/` y recarga la API al guardar:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

Solo hace falta `--build` si cambia `requirements.txt` o el `Dockerfile`. Una migración nueva se aplica con `docker compose restart api`.

Compose espera a que PostgreSQL esté listo; el backend aplica Alembic antes de iniciar y el frontend espera la salud de la API. La base usa un **volumen persistente**. `docker compose down` detiene el entorno conservando datos. `docker compose down -v` elimina definitivamente la base local. No ejecutar este último comando si necesitan conservarla.

Para levantar **solamente la base**:

```bash
docker compose up -d db
```

La base usa la imagen oficial de PostgreSQL; los Dockerfiles propios están en `backend/` y `frontend/`.

## Prueba de punta a punta en 2 minutos

1. Abrir la interfaz y elegir **Explorar demo**. Esto crea una marca y 18 piezas sintéticas, sin acceder a redes.
2. Abrir un tópico. Revisar evidencia temporal, gancho, afinidad y adaptación sugerida. Las URLs demo están deshabilitadas.
3. Filtrar temas y red. Inspeccionar valores de los gráficos y descargar un brief o el informe JSON desde el panel de método.
4. Crear una marca propia: nombre, descripción, audiencia, región y tópicos; opcionalmente enlaces y descripciones públicas.
5. En **Identidad de marca**, editar definición, tópicos y personas; guardar y confirmar.
6. En **Fuentes e integración**, importar el lote JSON generado por sus compañeros. El radar usa el lote seleccionado; no mezcla fuentes demo con públicas.

## Responsabilidades y límites del prototipo

| Paso | Implementado | Punto de extensión |
| --- | --- | --- |
| 1 · Identidad | Nombre y perfiles, Bright Data configurable con Meta/YouTube de respaldo, JSON de análisis, síntesis breve, pilares con evidencia, audiencias por validar y revisión humana | `backend/app/profiles.py`: conectores y enriquecimiento; `draft_identity`: base del brief; un LLM sigue pendiente |
| 2 · Descubrimiento | Contrato v1, validación, procedencia, separación demo/público, idempotencia de lotes. Instagram: creadores por tópico. LinkedIn + YouTube: radar de tendencias con brecha demanda/oferta y propuestas; exporta los videos como lote v1 | Otras fuentes: entregar `BatchCreate` a `POST /api/brands/{id}/trend-batches`. Radar: `backend/app/trends/` y `backend/app/trend_runs.py` |
| 3 · Informe editorial | Adaptadores para ambos motores y lotes v1, prioridades, series, evidencia y previews, propuestas, brief, filtros en URL y notas de calidad | `backend/app/editorial.py`, `frontend/src/EditorialWorkspace.tsx`; contrato `editorial-v1` |

**Bright Data recolecta perfiles públicos de marca en Instagram, YouTube y TikTok, y páginas de empresa de LinkedIn.** Meta y YouTube oficiales son respaldos para sus respectivas redes. TikTok puede reutilizar la caché del paso 2. No se admiten perfiles personales de LinkedIn. Los trabajos asíncronos persisten y no se reenvían automáticamente ante un inicio ambiguo. El paso 2 usa modelos según su configuración; el paso 3 presenta sus propuestas guardadas y añade reglas editoriales sin nuevas llamadas a modelos. La fuente y el equipo deben comprobar las condiciones aplicables a la recolección pública.

El prototipo responde: **“¿Qué temas de esta corrida priorizar, qué señales los respaldan y cómo probarlos con mi audiencia?”** Los estados de tendencia describen la muestra de cada motor; no representan un ranking de toda una plataforma. La confianza no es una probabilidad estadística y las explicaciones no atribuyen causalidad a gancho o formato.

Sin autenticación: entorno de equipo/local, con puertos Docker ligados a loopback. No desplegar públicamente sin aislamiento de usuarios, autenticación y límites de peticiones. El paso 3 no añade contactos ni listas de personas; conserva las referencias públicas y las métricas que los motores del paso 2 ya guardaron. Revisar los textos para excluir datos personales.

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
backend/app/trends/ Motor del radar LinkedIn + YouTube (paso 2)
backend/migrations/ Migraciones Alembic (base, análisis, trabajos)
backend/tests/      Pruebas de contrato y cálculo
frontend/src/       Interfaz React, TypeScript y CSS adaptable
docs/               Contrato del paso 2, radar de tendencias, ejemplo y arquitectura
compose.yaml        PostgreSQL + FastAPI + React servido por Nginx
```

## Trabajo en equipo

Leer primero [el contrato del paso 2](docs/step-2-contract.md). Conservar los nombres y tipos de sus campos. Si necesitan más campos, acuerden una versión nueva en vez de modificar silenciosamente `1.0`. El lote es una fotografía completa de una consulta, no un delta: sus compañeros deben agrupar en él todas las observaciones históricas que quieran comparar. Los lotes anteriores se conservan para consulta explícita; no se fusionan automáticamente.

Tecnología y arranque siguen las guías oficiales de [FastAPI](https://fastapi.tiangolo.com/tutorial/sql-databases/), [Vite](https://vite.dev/guide/) y [orden de inicio de Docker Compose](https://docs.docker.com/compose/how-tos/startup-order/).
