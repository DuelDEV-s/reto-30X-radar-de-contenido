# Análisis automático de perfiles · paso 1

El flujo ahora es **nombre y redes → Bright Data / respaldo oficial → JSON de perfil → propuesta de identidad → revisión → radar**. Se ejecuta al crear una marca con enlaces. También se pueden editar los enlaces y volver a consultar desde Identidad de marca.

No es el descubrimiento de tendencias del paso 2: aquí se entiende la propia marca. Los compañeros siguen entregando sus lotes de tendencias con el contrato existente.

Bright Data es el proveedor principal para ambas redes: seguir [su configuración y flujo asíncrono](bright-data.md). Las configuraciones oficiales siguientes son los respaldos y se mantienen opcionales cuando el proveedor principal responde.

## APIs oficiales disponibles como respaldo

| Red | Conector | Información solicitada | Límites |
| --- | --- | --- | --- |
| YouTube | Data API v3 | Descripción del canal, vistas acumuladas, suscriptores disponibles, total de videos y hasta 8 videos públicos recientes con sus vistas | Solo enlaces de canal `/@handle`, `/channel/UC…` o `/user/…`. No infiere Shorts. Las condiciones analíticas se configuran aparte. |
| Instagram | Meta Business Discovery, API con Facebook Login | Biografía, seguidores y publicaciones disponibles, muestra de hasta 8 publicaciones públicas y sus textos/formatos | Requiere acceso profesional autorizado. Esta consulta no pide Insights privados y no entrega vistas: quedan en `null`. |
| LinkedIn / TikTok | Pendiente | Enlace y descripción que aporte el equipo | Se muestran como conector no implementado, sin simular consulta. |

Las vistas y seguidores no se suman entre redes ni se usan para inventar un score de rendimiento. La interpretación v2 sintetiza el contexto sin concatenar publicaciones, elimina textos repetidos y organiza conceptos e intenciones editoriales con evidencia. El vocabulario cubre varios sectores; un sector sin coincidencias se declara como pendiente de revisión. La audiencia no se deduce como un hecho: si no se declara, queda por confirmar. No hay llamadas a un LLM en este flujo.

## Configurar YouTube

1. Crear un proyecto en Google Cloud y habilitar YouTube Data API v3.
2. Crear una clave y limitarla a esa API, con restricciones de aplicación apropiadas para su servidor.
3. En el `.env` local del repositorio, establecer `YOUTUBE_API_KEY`.
4. Mantener `YOUTUBE_ANALYTICS_APPROVED=false` mientras no se hayan satisfecho las condiciones aplicables al uso analítico. En ese estado se muestran los datos de la fuente, pero no se incorporan a la propuesta de identidad.
5. Si ya se ha obtenido la habilitación aplicable, el equipo puede declarar `YOUTUBE_ANALYTICS_APPROVED=true`. Es una declaración de configuración: no solicita ni concede permisos ante YouTube.

Documentación: [credenciales y API](https://developers.google.com/youtube/data/getting-started), [búsqueda del canal por handle](https://developers.google.com/youtube/data/reference/rest/v3/channels/list), [condiciones de métricas derivadas](https://developers.google.com/youtube/terms/derived-metrics-policy).

## Configurar Instagram

1. Preparar la aplicación de Meta y el acceso **Instagram API con Facebook Login**. Este conector no usa Instagram Login ni contraseñas o cookies de visitantes.
2. Disponer de la cuenta profesional vinculada a una página y de los permisos de lectura aplicables a Business Discovery para esa aplicación. Revisar los requisitos de desarrollo/revisión en Meta para los perfiles objetivo.
3. Obtener el token autorizado y el ID de la cuenta profesional que realiza la consulta. Solo configurar los valores en el backend.
4. Elegir una versión Graph API soportada por su aplicación; no copiar el valor ficticio `v99.0` usado en las pruebas.
5. Añadir al `.env`:

```dotenv
META_ACCESS_TOKEN=VALOR_LOCAL_NO_PUBLICAR
META_IG_USER_ID=ID_NUMERICO_DE_LA_CUENTA_PROFESIONAL
META_GRAPH_VERSION=VERSION_SOPORTADA_POR_SU_APP
```

La consulta usa el username de la URL de la marca en `business_discovery.username(...)`. No accede a perfiles personales ni intenta saltar una pantalla de login. Las credenciales de una aplicación son para la API autorizada; el contenido consultado debe seguir siendo público.

Fuentes de Meta: [guía de Business Discovery](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery/), [colección oficial de Instagram](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login).

## Aplicar la configuración

Las variables ya están conectadas al servicio API en `compose.yaml`. Una vez completado el `.env`:

```powershell
docker compose up --build -d
Invoke-RestMethod http://localhost:8000/api/profile-connectors
```

La respuesta del segundo comando indica qué conectores están configurados y qué nombres de variables faltan, sin devolver sus valores. No publicar la salida de `docker compose config` después de introducir claves: puede contener los secretos interpolados.

En la interfaz, crear una marca con nombre, enlaces y confirmación de que son cuentas públicas de la organización. La descripción, audiencia y tópicos manuales son opcionales. Si faltan credenciales se guarda la marca y se muestra la configuración requerida por red. Cuando se añadan las claves, usar **Consultar análisis**; no hace falta volver a crearla.

## JSON e integración

`GET /api/brands/{id}` incluye `profile_analysis`. Ejemplo de forma, con valores deliberadamente ausentes:

```json
{
  "schema_version": "1.0",
  "analyzed_at": "FECHA_REAL_DE_CONSULTA",
  "status": "unavailable",
  "profiles": [{
    "platform": "instagram",
    "url": "https://www.instagram.com/marca",
    "status": "requires_configuration",
    "provider": "meta_business_discovery",
    "description": "",
    "metrics": {"views": null, "followers": null, "posts": null},
    "content_sample": [],
    "usable_for_identity": false,
    "message": "Configuración pendiente"
  }],
  "suggested_identity": {},
  "identity_evidence": [],
  "opportunities": []
}
```

Es un esquema ilustrativo reducido, no un payload para importar. En la interfaz se puede ver y descargar el JSON completo del análisis real de cada marca.

Actualizar/analizar:

```text
POST /api/brands/{brand_id}/profiles/analyze
{"force": true}
```

También acepta `profiles`, `brand_accounts_confirmed` y `apply_to_identity`. Al reemplazar enlaces se debe confirmar que son cuentas públicas de marca. Las rutas de red se resuelven a endpoints fijos de Bright Data o de las APIs oficiales; el servidor no visita directamente las URLs aportadas.

Se conserva el resultado más reciente de la consulta y se reutiliza durante 15 minutos para reducir peticiones; `force: true` vuelve a consultar el análisis y los respaldos, pero reutiliza un trabajo Bright Data existente. Para otro trabajo terminado usar `refresh_bright_data: true` de forma explícita; puede consumir créditos. El estado `pending` se retoma sin esperar al TTL y la UI consulta automáticamente el mismo trabajo. Cambiar la configuración de disponibilidad invalida esa reutilización. No se crea historial de métricas del perfil. Los trabajos Bright Data tienen almacenamiento persistente separado para evitar reenvíos y conservan la fecha del resultado original. Si se almacenan datos de fuentes reales a largo plazo, implementar y verificar además sus reglas de retención y eliminación; esta versión todavía no incluye una purga programada.

## Cómo mejora la identidad y las recomendaciones

- Al crear la marca, los textos que puedan usarse se incorporan automáticamente al borrador y sugieren tópicos del vocabulario actual.
- Al actualizar perfiles, se muestra una propuesta separada. Una identidad confirmada no cambia hasta pulsar **Usar propuesta como borrador** y revisarla.
- Los tópicos de la identidad alimentan la afinidad del radar existente. Las métricas de perfil se muestran como contexto observado, no como evidencia de tendencia semanal.
- Las oportunidades de mejora se basan en la biografía y la muestra: completar una biografía vacía, hacer visibles los pilares detectados y proponer experimentos de formato para la audiencia declarada.

Los datos ausentes se representan con `null`; los fallos de red, falta de permisos y conectores pendientes tienen estados explícitos. Los errores de proveedores no se guardan en bruto, para no filtrar tokens. Se omiten correos y teléfonos reconocibles de textos obtenidos; eso no sustituye la revisión de que los perfiles sean institucionales y los textos no contengan otros datos personales.

## Verificación disponible

Las pruebas usan respuestas sintéticas de las APIs y cubren extracción, redacción de contactos, privacidad pública de videos, métricas ausentes, errores de proveedores, conservación de identidad confirmada y reutilización de consultas. Sin credenciales del equipo no se ha verificado el acceso en vivo a sus cuentas. Configurar una clave tampoco garantiza que un perfil concreto sea accesible con sus permisos.


## Interpretación v2 sin nueva recolección

En **Identidad de marca**, el botón **Reinterpretar datos guardados** usa exclusivamente las observaciones ya almacenadas. No consulta Bright Data, Meta, YouTube ni un modelo externo y no consume créditos de extracción. **Usar propuesta como borrador** también usa estos datos guardados; después se puede editar y confirmar la identidad.

```text
POST /api/brands/{id}/profiles/interpret
{"apply_to_identity": false}
```

La ruta devuelve 409 si no existe un análisis guardado. `apply_to_identity: true` aplica la propuesta explícitamente como borrador. La acción por defecto conserva la identidad actual, incluso si ya está confirmada. Los timestamps de observación y `analyzed_at` permanecen intactos; `interpreted_at` registra cuándo se reinterpretaron los textos.

El JSON añade `interpretation` con:

- `facts`: oferta o temas explícitos y foco local comunicado, con fragmentos y referencias. Se distingue el brief, texto manual, biografía y publicación.
- `pillars`: pilares propuestos, fundamento, idea editorial, qué medir y evidencia. Una pieza aislada ajena a la oferta no redefine los temas principales.
- `audience_hypotheses`: ocasiones y necesidades por validar, sin inventar edad, género, poder adquisitivo ni compradores observados. La audiencia que declaró el equipo se conserva.
- `coverage` y `limitations`: número de textos distintos y piezas disponibles, vistas o formatos ausentes y límites del método.

El foco local se extrae de expresiones de servicio/ubicación, como «Domicilios Ibagué», no de menciones arbitrarias en un post viral. Una región general predeterminada puede proponerse más específica; una región explícita distinta se conserva y se señala la diferencia. El equipo revisa cobertura y pertinencia antes de confirmar.

No se calculan rankings de publicaciones, crecimiento ni supuesta eficacia de un formato a partir de esta interpretación. Las ideas de contenido son propuestas para un experimento nuevo. Los contadores se muestran como contexto; no determinan el resumen ni las audiencias.

Es un motor local de reglas y evidencias, con vocabulario ampliable; puede perder matices y no sustituye un análisis semántico con un modelo. El contrato estructurado permite añadir ese proveedor después conservando validación, citas y revisión humana.
