# Creadores de TikTok

Búsqueda de creadores por tópico en TikTok, con el mismo flujo que Instagram: candidatos → perfiles → revisión LLM de cuentas → posts y línea base → relevancia de cada post → tendencias. La diferencia está en el arranque: en vez de Google, el propio scraper de Bright Data busca **videos por palabra clave**, y sus autores son los candidatos.

En la interfaz: **Descubrimiento → ¿Dónde buscamos? → TikTok**. Cada corrida queda en el historial de la marca, separada de las de Instagram.

## Flujo

| Paso | Qué hace | Bright Data |
| --- | --- | --- |
| 1 · Palabras clave | Las mismas reglas que las queries de Instagram, sin `site:` ni comillas | — |
| 2 · Videos | Busca hasta `TIKTOK_VIDEOS_PER_KEYWORD` (20) videos por palabra clave. Asíncrono: la vista consulta el avance | Posts `gd_lu702nij2f790tmv9h`, *discover by keyword* |
| 3 · Candidatos | Autores de los videos, filtrados y ordenados (ver abajo) | — |
| 4 · Perfiles | Ficha de cada candidato; solo se pagan los que no estén en `tiktok_accounts` o tengan la ficha vencida (`TIKTOK_PROFILE_TTL_DAYS`, 30) | Profiles `gd_l1villgoiiidt09ci` |
| 5 · Revisión LLM | El mismo veredicto que en Instagram (relevancia, tipo de cuenta, interna). La evidencia incluye las descripciones de sus videos encontrados en la búsqueda | — |
| 6 · Posts | Últimos 30 días, máx. 30 videos por creador aprobado, `BRIGHT_DATA_MAX_POST_CREATORS` (15) creadores | Posts, *discover by profile_url* |
| 7 · Tendencias | Igual que Instagram, con umbrales de tracción propios | — |

No hay paso 8: los patrones de producción con Gemini necesitan el MP4, y el CDN de TikTok no deja descargarlo sin sesión (403). El endpoint de patrones responde 409 en corridas de TikTok.

API: `POST /api/brands/{id}/tiktok-search` (`{"topic": "...", "max_queries": 3, "videos_per_keyword": 20}`) crea la corrida y responde 202; `GET /api/discovery-runs/{run_id}` avanza la búsqueda sin iniciar otra. Perfiles, posts y tendencias usan los mismos endpoints de corrida que Instagram. Fichas guardadas: `GET /api/tiktok-accounts/{username}` y `/avatar`.

## Candidatos útiles, no cualquier video

Cualquier video viral suelto aparece en la búsqueda. Antes de pagar perfiles (`backend/app/tiktok_search.py`):

- Se descartan los videos de cuentas de la marca (perfil de TikTok en el brief), de autores con menos de `TIKTOK_MIN_FOLLOWERS` (5.000) seguidores y de autores que solo aparecen con videos de hace más de `TIKTOK_MAX_VIDEO_AGE_DAYS` (180) días. Cada video descartado guarda el motivo.
- Se ordena primero por **palabras clave distintas** en las que aparece el autor (constancia en el tema), luego por videos encontrados, vistas medianas y mejor posición.
- Solo los primeros `TIKTOK_MAX_CANDIDATES` (20) pasan a perfiles. Después filtran la revisión LLM y la línea base, como en Instagram.

## Métricas

TikTok sí entrega vistas (`play_count`), además de likes (`digg_count`), compartidos, guardados y comentarios. El rendimiento de cada video frente a su creador pondera vistas 0,5, likes 0,25, compartidos 0,15 y comentarios 0,1; la confianza depende de la base de vistas. Instagram conserva likes 0,7 y comentarios 0,3.

**Tendencias:** con la misma mediana (~×1), el rendimiento en TikTok es mucho más disperso: en la primera corrida real el p75 fue ×3,0 frente a ×1,6 en Instagram (unas 2,2 veces más ancho en escala logarítmica). Por eso "en caliente" exige tracción ×2,5 (Instagram ×1,5) y "consolidado" ×1,5 (Instagram ×1,2).

## Transcripción

Sin descargar el video: TikTok publica subtítulos automáticos en WebVTT y Bright Data los entrega en `subtitle_url`. Se usan los de los primeros `TRANSCRIPT_MAX_SECONDS` (30 s), sin costo de OpenAI. Como en Instagram, solo para videos que la revisión marcó relevantes o indeterminados. Unos 5 de cada 6 videos traen subtítulos; los demás se clasifican con su descripción.

## Datos

- `tiktok_accounts`: ficha del perfil (seguidores, likes totales, videos, verificado, región, enlaces, avatar) y registro completo en `raw`.
- `tiktok_posts` y `tiktok_post_observations`: un video por id, con vistas, likes, comentarios, compartidos y guardados, y una observación por recolección. Los videos de la búsqueda también se guardan.
- `account_reviews`, `post_topic_reviews` y `post_content_analyses` tienen columna `platform`: el mismo @usuario o id puede existir en las dos redes. Migración `013`.

## Tiempos y costo

En la primera corrida real (3 palabras clave × 20 videos): la búsqueda tardó ~9 min, los perfiles de 18 cuentas ~6 min y los videos de 15 creadores ~18 min (365 videos). Buscar por palabra clave y recoger varios perfiles tarda más que el tope general de Bright Data, así que tienen sus propios topes: `TIKTOK_SEARCH_TIMEOUT_SECONDS` y `TIKTOK_POSTS_TIMEOUT_SECONDS` (45 min). Cada video y cada perfil es un registro facturable; para pruebas, bajar `TIKTOK_VIDEOS_PER_KEYWORD`, `TIKTOK_MAX_CANDIDATES` y `BRIGHT_DATA_MAX_POST_CREATORS`.
