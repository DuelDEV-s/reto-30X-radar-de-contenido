# Pasar de la demo a datos reales

La aplicación ya arranca y guarda información real en PostgreSQL. Lo pendiente es integrar la adquisición de contenido y un proveedor de IA. **Agregar claves al `.env` no implementa esas integraciones.** Esta guía separa configuración existente de desarrollo pendiente.

## 1. Preparar el entorno del equipo

Con Docker Desktop y el motor Linux encendidos:

```powershell
git clone https://github.com/DuelDEV-s/reto-30X-radar-de-contenido.git
cd reto-30X-radar-de-contenido
Copy-Item .env.example .env
# Revisar .env antes del primer arranque.
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health
```

Si ya existe `.env`, conservarlo. Los únicos valores implementados hoy son los de `.env.example`: base de datos y configuración local. En Compose, el origen CORS está fijado en `compose.yaml`; la variable de la plantilla sirve al backend ejecutado fuera de Docker cuando se exporta en su terminal. `.env` no se lee automáticamente en Python local.

Interfaz: http://localhost:5173. Swagger: http://localhost:8000/docs. PostgreSQL desde el host: `localhost:15432`; desde el contenedor API: `db:5432`. En Docker no usar la URL SQLite de la plantilla para reemplazar la conexión PostgreSQL que ya configura Compose.

La contraseña de ejemplo es para desarrollo local. Establecer la propia antes de inicializar una base nueva; si el volumen ya existe, cambiar el archivo no cambia la contraseña del usuario PostgreSQL. No borrar el volumen para resolverlo si contiene datos que deban conservarse.

## 2. Crear y confirmar una marca real — paso 1

En **Nueva marca**, introducir nombre, propuesta, audiencia, región y tópicos. Añadir referencias públicas de la organización y sus descripciones, revisando que no incluyan datos personales.

En **Identidad de marca**, corregir definición y personas, y guardar la confirmación. Hoy esto funciona con revisión humana: los enlaces no se navegan y las descripciones de perfiles no se analizan automáticamente. Este paso no necesita ninguna API key.

## 3. Conectar la fuente de los compañeros — paso 2

El equipo debe escoger una fuente que permita tanto obtener contenido público como reutilizar sus datos para el análisis propuesto. Registrar método, procedencia y condiciones aplicables. Un dataset abierto también necesita permiso compatible; copiar manualmente o cambiar la etiqueta del método no elimina las condiciones de la fuente.

Para una primera entrega, preparar un lote pequeño de contenido real con métricas verificadas y procedencia. Enviarlo a:

```text
POST /api/brands/{brand_id}/trend-batches
Content-Type: application/json
```

Consultar [el contrato v1](step-2-contract.md) y el esquema `BatchCreate` en Swagger. Marcar `mode: "public"` únicamente para observaciones reales y usar el método correspondiente (`official_api`, `open_dataset` o `manual_public`). `compliance_confirmed` es una declaración del proveedor, no una verificación automática.

El adaptador del paso 2 todavía debe implementarse. Debe:

1. Descubrir piezas por los tópicos de `GET /api/brands/{id}`.
2. Mantener IDs estables, normalizar tópicos y excluir campos personales.
3. Guardar observaciones reales con fecha y zona horaria.
4. Reunir el historial completo de cada pieza en `snapshots` y entregar un lote por consulta.
5. Manejar límites de peticiones, errores, deduplicación y reglas de actualización o eliminación exigidas por la fuente.

El contrato actual exige un gancho. Si no se ha observado la apertura, no inventarlo ni tratar el título como transcripción: completar la revisión editorial antes de importar, o acordar una versión del contrato que acepte ese dato ausente. Igualmente, si una fuente no expone vistas, hay que ampliar el contrato para otra métrica; no poner likes o impresiones en `views`.

### Si consideran YouTube

Para acceder técnicamente a datos públicos: crear un proyecto en Google Cloud, habilitar YouTube Data API v3 y obtener una API key. El descubrimiento usa `search.list`; el recurso `videos.list` permite consultar metadatos y estadísticas. Revisar la cuota de su proyecto. [Inicio oficial](https://developers.google.com/youtube/data/getting-started), [búsqueda](https://developers.google.com/youtube/data/reference/rest/v3/search/list), [videos](https://developers.google.com/youtube/data/reference/rest/v3/videos/list).

**Antes de conectar estos datos al score:** las políticas generales restringen métricas derivadas y agregación; las condiciones adicionales de analítica requieren el proceso de aceptación/aprobación aplicable. No asumir que crear la key autoriza este radar. La retención también debe ajustarse a las condiciones de acceso. [Políticas](https://developers.google.com/youtube/terms/developer-policies), [condiciones adicionales](https://developers.google.com/youtube/terms/derived-metrics-policy).

Si el uso está habilitado y se implementa el adaptador, el contrato v1 acepta `https://youtu.be/ID_DEL_VIDEO`. La URL `youtube.com/watch?v=...` actualmente se rechaza porque contiene parámetros. El ejemplo de documentación tiene datos ficticios y no debe convertirse en un lote público.

Para LinkedIn, Instagram y TikTok, verificar con el equipo qué acceso y uso permite su fuente concreta. La aplicación no incluye un conector universal a las cuatro redes.

## 4. Obtener historia temporal real

Con una observación por pieza se pueden ver vistas, pero no aceleración. Con dos se puede calcular una velocidad. Se necesitan **tres observaciones y una velocidad previa positiva** para comparar las dos últimas velocidades; la aplicación ya refleja los casos sin evidencia suficiente.

El equipo debe ejecutar su recolector periódicamente, por ejemplo cada seis horas como decisión inicial a validar con la fuente y su cuota. El planificador/recolector no está implementado. Los lotes no se fusionan automáticamente: cada nueva entrega debe incluir el historial que quieren analizar.

Tres muestras del mismo día permiten una comparación de esos intervalos; no prueban crecimiento durante una semana. Para responder una pregunta semanal hace falta recoger esa historia o disponer de un conjunto histórico cuyo uso esté permitido. No fabricar fechas ni repetir el mismo valor como si fueran mediciones independientes.

## 5. Integrar IA/JEV — pasos 1 y 3

Elegir proveedor y modelo, obtener credenciales de servidor y confirmar su endpoint, autenticación y formato de respuesta. El acceso a JEV no está configurado ni se presupone un contrato de API.

Desarrollo pendiente en `backend/app/services.py`:

- **`draft_identity`:** enviar el brief y los textos públicos aportados para proponer definición, tópicos y segmentos. Validar la respuesta con `Identity`, mantenerla en borrador y conservar revisión humana.
- **Esquema de procedencia:** `Identity.method` hoy solo admite `brief_rules` y `human_review`; ampliarlo y actualizar los tipos del frontend si se añade generación con modelo. Registrar proveedor/modelo de forma explícita.
- **`analyze`:** conservar los cálculos numéricos en Python. Pedir al modelo hipótesis editoriales y adaptaciones basadas en la evidencia disponible, con referencias a las piezas y sin atribuir causalidad.
- Validar la salida, limitar tokens/costo, añadir timeout y manejar errores. Si se usan reglas como alternativa, identificarlas en el resultado y actualizar los textos de la interfaz que hoy dicen que no hay IA.

Variables **propuestas, aún no implementadas**: `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` y las credenciales del recolector, por ejemplo `YOUTUBE_API_KEY` si corresponde. Para usarlas hay que añadir lectura de configuración al backend/adaptador y pasarlas expresamente mediante `environment` o `env_file` en el servicio correspondiente de Compose. Nunca incluir claves en `VITE_*`, Git, payloads de procedencia o logs. La key de la fuente puede quedarse exclusivamente en el proceso recolector si este vive fuera del backend.

## 6. Verificar el circuito completo

1. Crear una marca real y confirmar su identidad.
2. Importar un lote pequeño de una fuente permitida y comprobar enlaces, textos, vistas y fechas contra esa fuente.
3. Confirmar que el informe identifica `mode: "public"`; los fixtures siguen en `demo`.
4. Incorporar dos observaciones adicionales reales, cuando transcurra el intervalo definido, y entregar un nuevo lote con las tres.
5. Revisar `GET /api/brands/{id}/report?batch_id={batch_id}` y contrastar manualmente una aceleración calculada.
6. Si se integra IA, comprobar que referencias y métricas no cambian y que las hipótesis están etiquetadas.
7. Reiniciar los servicios sin eliminar volúmenes y comprobar que marcas y lotes permanecen.

Para compartir una instancia por Internet todavía hacen falta autenticación, separación de usuarios, HTTPS, límites y gestión de secretos/retención. El Compose actual está preparado para uso local y publica puertos solo en loopback.

## Reparto para la hackathon

| Responsable | Siguiente entrega |
| --- | --- |
| Tu equipo del paso 2 | Primera fuente permitida + lote público v1 + historial real |
| Tú / integración backend | Adaptador del proveedor IA, validación de salida y procedencia |
| Equipo editorial | Identidad confirmada, revisión de ganchos y pertinencia de propuestas |
| Integración conjunta | Una demostración de punta a punta, separando observado, calculado e inferido |

La aplicación puede trabajar con datos reales y reglas editoriales sin un LLM. La automatización del descubrimiento y las explicaciones generadas por IA son integraciones adicionales, no opciones que hoy se activen solo con una clave.
