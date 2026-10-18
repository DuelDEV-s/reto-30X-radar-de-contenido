# Configuración real de los tres pasos

El prototipo tiene identidad de marca, descubrimiento y un informe editorial. No hace falta otra clave para el paso 3: lee lo que el paso 2 ya guardó.

## 1. Actualizar y levantar el entorno

Desde la raíz del repositorio, conservar el `.env` existente. Si no existe, copiar `.env.example` a `.env` y completar las variables necesarias. No subir ese archivo a Git.

```bash
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Docker Desktop debe tener activo su motor Linux. Compose aplica las migraciones existentes al iniciar la API y conserva los volúmenes de PostgreSQL y del radar. No usar `down -v` para actualizar.

Interfaz: http://localhost:5173. API: http://localhost:8000/docs. PostgreSQL desde el host: `localhost:15432`; desde la API: `db:5432`.

## 2. Paso 1: perfiles públicos de marca

| Red | Configuración del proveedor principal | Alcance |
| --- | --- | --- |
| Instagram | `BRIGHT_DATA_API_KEY` + `BRIGHT_DATA_INSTAGRAM_DATASET_ID` | Biografía, seguidores, publicaciones y muestra disponible |
| YouTube | `BRIGHT_DATA_API_KEY` + `BRIGHT_DATA_YOUTUBE_DATASET_ID` | Descripción del canal y contadores disponibles |
| TikTok | `BRIGHT_DATA_API_KEY`; ID opcional `BRIGHT_DATA_TIKTOK_PROFILES_DATASET_ID` | Biografía, seguidores y total de videos. Valor por defecto `gd_l1villgoiiidt09ci` |
| LinkedIn | `BRIGHT_DATA_API_KEY`; ID opcional `BRIGHT_DATA_LINKEDIN_COMPANIES_DATASET_ID` | Páginas `/company/`: descripción, especialidades y seguidores. Valor por defecto `gd_l1vikfnt1wgvvqz95w` |

Comprobar que los scrapers estén habilitados en la cuenta de Bright Data y que el plan tenga saldo/cuota. La presencia de variables no valida credenciales en vivo. TikTok reutiliza perfiles públicos vigentes del paso 2; una nueva recolección explícita sí puede consumir créditos.

Meta Business Discovery es respaldo de Instagram (`META_ACCESS_TOKEN`, `META_IG_USER_ID`, `META_GRAPH_VERSION`); `YOUTUBE_API_KEY` permite el respaldo oficial de YouTube. LinkedIn y TikTok no tienen API oficial de respaldo implementada. [Configuración y contrato completo](bright-data.md).

Después de cambiar `.env`, recrear la API:

```bash
docker compose up -d --force-recreate api
```

Python local no carga `.env` automáticamente: exportar variables en su terminal. Las claves nunca se configuran como `VITE_*` ni se envían al frontend.

## 3. Paso 2: elegir el motor

**Instagram:** configurar Bright Data, la zona SERP (`BRIGHT_DATA_SERP_ZONE`) y los scrapers de perfiles y posts. `OPENAI_API_KEY` habilita revisión de cuentas, relevancia y agrupación temática. `GEMINI_API_KEY` y el modelo correspondiente habilitan el análisis de producción cuando está disponible. Revisar [líneas base y revisión de posts](post-relevance.md).

**TikTok:** usa la misma key de Bright Data para buscar videos por palabra clave y obtener perfiles/posts. Los IDs tienen valores publicados predeterminados. La revisión temática usa OpenAI. El análisis audiovisual descargado de TikTok no está disponible: no se intenta saltar las restricciones de su CDN. [Variables y flujo de TikTok](tiktok.md).

**LinkedIn/YouTube:** el motor integrado usa `EXA_API_KEY`, `YOUTUBE_API_KEY` y `ANTHROPIC_API_KEY` según su configuración actual; `BRAVE_API_KEY` amplía la búsqueda de LinkedIn. Ver [modelo, presupuesto y variables del radar](trend-radar.md). El presupuesto predeterminado de corrida es `RUN_BUDGET_USD=6`; no es un límite global de la cuenta. Configurar cuotas en los proveedores. La política de uso aplicable a los datos de YouTube debe estar verificada por el equipo.

Iniciar una corrida desde Descubrimiento puede consumir créditos de recolección y modelos. Las consultas de avance del paso 2 pueden procesar tandas pendientes; esto es distinto del informe del paso 3, que solo lee datos guardados.

## 4. Paso 3: revisar y producir

Elegir la marca, pulsar **Ver informe editorial** al terminar el paso 2 o abrir **Radar de contenido** y seleccionar la corrida. No requiere una API key nueva. Revisar prioridades, series, señales, encaje con marca y evidencia antes de usar la propuesta. La preview se carga al pulsarla y puede quedar bloqueada por la plataforma; siempre se conserva el enlace original cuando existe. [Flujo y método](editorial-radar.md).

Si no aparecen temas, comprobar que la corrida tenga publicaciones y revisiones temáticas guardadas con línea base calculable. Sin agrupación semántica, se muestran etiquetas exactas como agrupación provisional. Las notas de cobertura indican qué falta. Una corrida de LinkedIn/YouTube debe terminar y guardar su reporte.

## 5. Verificación sin gasto

**Explorar demo** genera una marca y 18 piezas ficticias. Permite probar ranking, selección, filtros, series, brief y exportación sin proveedores. Las URLs ficticias no se abren ni generan previews. Para pruebas automatizadas:

```bash
cd backend
python -m pytest -q
cd ../frontend
npm ci
npm run build
```

Los lotes v1 de otros recolectores siguen admitidos mediante `POST /api/brands/{id}/trend-batches`; ver [contrato de lotes](step-2-contract.md). El informe conserva separado cada lote y corrida. Tres observaciones permiten comparar velocidades del lote; no sustituyen una historia semanal real ni una muestra representativa.

La instancia de Compose está pensada para el equipo/local. Antes de exponerla por Internet hacen falta autenticación, separación de usuarios, HTTPS y gestión de cuotas y retención.
