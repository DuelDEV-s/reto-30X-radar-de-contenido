# Bright Data principal, APIs oficiales de respaldo

El paso 1 consulta perfiles **de Instagram y canales de YouTube** mediante Bright Data. Si falta configuración, hay un error, cuota agotada o el trabajo excede su plazo, intenta Meta Business Discovery para Instagram o YouTube Data API para YouTube. Cada resultado registra `provider`, `attempts`, `fallback_used` y el estado de `collection`.

El paso 1 también admite cuentas públicas de marca de TikTok (`/@cuenta`) y páginas públicas de empresa de LinkedIn (`/company/nombre`). Los perfiles personales `/in/` se rechazan. No añade un LLM ni reemplaza los motores del paso 2.

TikTok usa `BRIGHT_DATA_TIKTOK_PROFILES_DATASET_ID`, con valor publicado predeterminado `gd_l1villgoiiidt09ci`; es el mismo conector de perfiles del paso 2. LinkedIn usa `BRIGHT_DATA_LINKEDIN_COMPANIES_DATASET_ID`, predeterminado `gd_l1vikfnt1wgvvqz95w`. Ambos usan `BRIGHT_DATA_API_KEY`; no requieren Meta. Confirmar acceso y cuota de esos scrapers en la cuenta. Si existe una ficha pública y vigente de TikTok en la caché del paso 2, se reutiliza sin iniciar otra extracción (salvo **Nueva recolección** explícita).

Contratos publicados de Bright Data: [TikTok Profiles](https://docs.brightdata.com/scrapers/gd_l1villgoiiidt09ci.json) y [LinkedIn Companies](https://docs.brightdata.com/scrapers/gd_l1vikfnt1wgvvqz95w.json). Los conectores están cubiertos con fixtures; eso no confirma el acceso de una cuenta real del proveedor.

## Configurar en cinco pasos

1. Crear o usar una cuenta de Bright Data y obtener una API key con acceso a Web Scraper API. Configurar presupuesto y alertas en el proveedor según su cuenta; el límite local de trabajos no es un límite monetario mensual.
2. Comprobar en su catálogo el scraper **Instagram Profiles** y **YouTube Channel**. La plantilla propone los IDs publicados `gd_l1vikfch901nx3by4` y `gd_lk538t2k2p1k3oos71`; confirmar que están habilitados y que conservan los campos del contrato indicado abajo. Un scraper de publicaciones o videos es otro producto y no es intercambiable con estos perfiles.
3. Copiar `.env.example` a `.env` solo si aún no existe. Completar en ese archivo local:

```dotenv
BRIGHT_DATA_API_KEY=SU_CLAVE_LOCAL
BRIGHT_DATA_INSTAGRAM_DATASET_ID=gd_l1vikfch901nx3by4
BRIGHT_DATA_YOUTUBE_DATASET_ID=gd_lk538t2k2p1k3oos71
BRIGHT_DATA_MAX_NEW_JOBS_PER_ANALYSIS=4
BRIGHT_DATA_JOB_TIMEOUT_SECONDS=600
```

4. Para disponer además del respaldo, configurar las variables oficiales descritas en [análisis de perfiles](profile-analysis.md): `META_ACCESS_TOKEN`, `META_IG_USER_ID`, `META_GRAPH_VERSION` y/o `YOUTUBE_API_KEY`. Son opcionales si Bright Data responde. La declaración `YOUTUBE_ANALYTICS_APPROVED` sigue controlando el uso del texto obtenido por la API oficial en la identidad.
5. Recrear los servicios y consultar disponibilidad:

```powershell
docker compose up --build -d
Invoke-RestMethod http://localhost:8000/api/profile-connectors
```

La respuesta expone nombres de variables pendientes y las rutas `primary` y `fallback`; no expone las claves. `configured: true` significa que las variables están presentes, no que sus credenciales hayan sido verificadas en vivo. Python local requiere exportarlas en la terminal: no lee `.env` automáticamente.

En la interfaz, crear una marca con nombre, URLs y confirmación de cuentas públicas institucionales. Si ya existe, elegir **Consultar análisis**. El primer trabajo puede consumir créditos del proveedor. No compartir claves en el chat ni en Git.

## Trabajos asíncronos y actualización

- El backend guarda una reserva en PostgreSQL **antes** de enviar `POST /datasets/v3/trigger`. Envía un solo perfil por trabajo, `limit_per_input: 1`, sin cookies, contraseñas ni sesiones de redes.
- Guarda el `snapshot_id`, devuelve `pending` y la interfaz consulta cada cuatro segundos mientras esa marca está abierta. Retoma el mismo trabajo con `GET /progress/{snapshot_id}` y descarga `GET /snapshot/{snapshot_id}?format=json` cuando está listo. Cerrar la página pausa estas consultas; volver a abrir la marca las retoma. No hay un trabajador separado en segundo plano.
- Las consultas automáticas solo retoman trabajos existentes. No inician los perfiles que quedaron pendientes por el límite local. **Consultar análisis** permite iniciar esos perfiles aún sin trabajo.
- Los trabajos y resultados normalizados sobreviven al reinicio de la API. `force: true` recalcula el análisis, consulta los trabajos pendientes y vuelve a intentar el respaldo oficial; **no vuelve a pagar automáticamente por una extracción Bright Data ya guardada**. Un resultado terminado se conserva con su fecha original, incluso después de los 15 minutos de caché del análisis.
- Para obtener una nueva observación de un perfil ya extraído, pulsar **Nueva recolección**. Equivale a `{"force": true, "refresh_bright_data": true}`; puede consumir créditos. Mientras un trabajo siga activo se retoma ese trabajo, incluso con esa opción.
- Si un timeout o una respuesta ambigua impide confirmar el inicio, queda `unknown`. Se intenta el respaldo y no se reenvía el POST automáticamente. Revisar el panel de Bright Data antes de solicitar otra recolección: la anterior podría haberse iniciado.
- El plazo predeterminado es 600 segundos desde el inicio, comprobado al consultar; se acepta entre 30 y 3600. Vencerlo activa el respaldo sin cancelar ni duplicar el trabajo remoto. El límite predeterminado es cuatro trabajos nuevos **por petición de análisis**, configurable entre uno y ocho. No limita acumulación entre marcas, clics o procesos; los límites de gasto se gestionan en el proveedor.

La creación enriquece el borrador cuando termina el trabajo si ese borrador sigue intacto. Una identidad que el equipo editó o confirmó se conserva. **Usar propuesta como borrador** aplica la propuesta de forma explícita.

## Contrato y datos conservados

API fija: `https://api.brightdata.com/datasets/v3`, autenticación Bearer. El `dataset_id` identifica el scraper, no una base de datos que deban crear. No se siguen redirecciones del cliente HTTP ni se visitan desde el backend hosts aportados por el usuario.

Se solicitan únicamente estos campos mediante `custom_output_fields`:

| Scraper | Campos |
| --- | --- |
| Instagram Profiles | `url`, `profile_url`, `account`, `biography`, `followers`, `posts_count`, `is_private`, `posts` |
| YouTube Channel | `url`, `name`, `Description`, `subscribers`, `videos_count`, `views`, `top_videos` |
| TikTok Profiles | `url`, `account_id`, `nickname`, `biography`, `signature`, `followers`, `videos_count`, `is_private` |
| LinkedIn Companies | `url`, `name`, `about`, `description`, `slogan`, `specialties`, `industries`, `followers` |

Se valida que la URL de respuesta coincida con la solicitada y, en Instagram/TikTok, que `is_private` sea expresamente `false`. Una fuente marcada privada o que requiere login se descarta **sin probar otro proveedor para ese contenido**. Una respuesta incompleta o incompatible no se convierte en datos ficticios. LinkedIn conserva descripción, especialidades y seguidores de empresa; no pide empleados, alumni o contactos. TikTok conserva biografía, seguidores y total de videos; sus likes no se interpretan como vistas. Las vistas de perfil ausentes quedan en `null`.

Solo se almacena el resultado normalizado: descripción, contadores agregados disponibles, hasta ocho piezas, referencias públicas y fechas. No se guarda el JSON bruto de Bright Data, autores, comentarios, imágenes, contactos o listas de seguidores. Se omiten correos y teléfonos reconocibles del texto; el equipo debe revisar otros posibles datos personales y trabajar únicamente con cuentas de organización. Las URLs de piezas se reducen a identificadores públicos, quitando parámetros de seguimiento.

`views` del perfil Instagram permanece en `null`: este scraper no entrega ese total. Solo se conservan vistas de piezas cuando la respuesta las trae explícitamente. No se lanzan scrapers adicionales de Reels. `top_videos` no prueba que una muestra sea reciente; los formatos desconocidos se muestran como tales. Los contadores abreviados ambiguos, negativos o ausentes quedan en `null`.

Las credenciales de Bright Data autentican contra su servicio; no son un login a Instagram o YouTube. La configuración no envía credenciales de redes. El proveedor y el equipo deben asegurar que la fuente y el uso concreto cumplen las condiciones del reto y las condiciones aplicables; la visibilidad pública por sí sola no verifica esos permisos. Esta versión no incluye purga programada de datos ni aislamiento para una instancia pública multiusuario.

## Verificación

Las pruebas usan HTTP simulado y respuestas sintéticas. Cubren proveedor principal, respaldos, estados pendientes/fallidos, timeout ambiguo, límites, persistencia, normalización y conservación de identidad. No se ejecutan extracciones de pago durante estas comprobaciones. Sin las claves del equipo no se ha verificado el acceso real a sus perfiles.

Referencias del proveedor: [solicitudes asíncronas y parámetros](https://docs.brightdata.com/api-reference/rest-api/scraper/asynchronous-requests), [contrato publicado de Instagram Profiles](https://docs.brightdata.com/scrapers/gd_l1vikfch901nx3by4.json), [contrato publicado de YouTube Channel](https://docs.brightdata.com/scrapers/gd_lk538t2k2p1k3oos71.json).


## Diagnosticar un inicio fallido

La clave presente en `.env` no garantiza que una recolección se haya iniciado. Los nuevos intentos distinguen:

- `http_400` / `http_422`: parámetros o formato rechazados; muestra únicamente nombres de campos conocidos, sin copiar el cuerpo de error.
- `dataset_not_found`: HTTP 404, revisar ID y disponibilidad del scraper.
- `access_denied`, `balance`, `quota`: acceso, saldo o límite del proveedor.
- `connection_failed`: no fue posible conectar desde el contenedor (red, DNS, TLS).
- `trigger_timeout`, `http_408`, `http_5xx`, `invalid_json` o `missing_snapshot_id`: no se pudo confirmar el inicio. Se conserva `unknown`, sin reenviar automáticamente.
- `legacy_unknown`: intento de una versión anterior que no guardó la causa. No es posible reconstruir retrospectivamente su respuesta HTTP; revisar el panel antes de usar Nueva recolección.

El código se conserva en `attempts[].code` y, en los intentos nuevos, `collection.error_code`. El POST de inicio dispone ahora de 25 segundos para responder (antes 8), con conexión limitada a 5 segundos. Las consultas de snapshots mantienen el timeout general; el límite por perfil es 55 segundos. El proxy local permite hasta 180 segundos por análisis, para no cortar los grupos de perfiles antes que la API.

Consultar análisis reutiliza también los intentos fallidos guardados. Tras corregir la configuración o el conector, **Nueva recolección** crea otro intento y puede consumir créditos. No borrar el volumen PostgreSQL para resolver un fallo del proveedor.
