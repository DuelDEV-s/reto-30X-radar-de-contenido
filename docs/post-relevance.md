# Línea base y relevancia de posts

Paso 6 de la búsqueda por tópico. Con los creadores que pasan la revisión LLM, el radar trae sus posts recientes y mide cuáles rindieron por encima de lo normal **para ese creador**. Es la base para separar lo que siempre se publica de lo que está en tendencia.

## Recolección

`POST /api/discovery-runs/{run_id}/posts` inicia la recolección; `GET` del mismo recurso consulta el trabajo en curso (nunca inicia otro) y devuelve el análisis.

- Scraper: Instagram Posts, *discover by URL* (`BRIGHT_DATA_INSTAGRAM_POSTS_DATASET_ID`, por defecto `gd_lk5ns7kz21pck8jpis`). Por creador: `num_of_posts=30`, `start_date`/`end_date` de los últimos 30 días y `limit_per_input=30` como tope de facturación.
- Creadores: los que la revisión LLM incluye (externos, relevancia alta o media, creador o empresa afín). Sin `OPENAI_API_KEY`, todos los perfiles públicos de la corrida. Nunca cuentas privadas ni sin ficha. Se excluyen las cuentas con menos de `INSTAGRAM_MIN_FOLLOWERS` (2.000) seguidores o sin dato de seguidores: con tan poca audiencia las interacciones son pocas y muy variables, y la línea base es ruido. La respuesta las lista en `excluded_small`. Como mucho `BRIGHT_DATA_MAX_POST_CREATORS` (15) por corrida.
- Un solo scraper para todos los formatos. Se evaluó separar reels (`gd_lyclm20il4r5helnj`) y posts para obtener vistas, pero en octubre de 2026 ninguno las entrega: ni Posts por descubrimiento, ni Reels por descubrimiento, ni Reels pedidos por URL directa (prueba con 3 reels: `views` y `video_play_count` en `null`). Separarlos solo duplicaría trabajos sin aportar la señal.
- La descarga del snapshot puede responder `202 {"status": "building"}` aunque el progreso diga `ready`; se trata como "sigue en proceso" y se vuelve a consultar.
- Costo: un creador cuyos posts se recogieron hace menos de `INSTAGRAM_POSTS_TTL_HOURS` (24 h) se reutiliza sin pagar. El POST facturable se reserva con una transición condicional, igual que los perfiles: dos clics no inician dos trabajos y un inicio sin confirmar no se reenvía.

## Almacenamiento

- `instagram_posts`: un registro por shortcode, compartido entre marcas. Campos normalizados (tipo, caption, hashtags, fecha, likes, comentarios, vistas y reproducciones si algún día llegan, duración, seguidores al observar, patrocinio, fijado, coautores, etiquetados, audio) y el registro completo de Bright Data en `raw`. El scraper usa nombres distintos según la versión (`comments`/`num_comments`, `datetime`/`date_posted`); se aceptan todos.
- `instagram_post_observations`: las métricas de cada post en cada recolección. Volver a recoger un creador añade una observación; con dos o más se mide la velocidad real (likes y comentarios por hora entre la primera y la última lectura, separadas al menos 6 h) y se puede calibrar la curva de madurez.
- Likes ocultos (Instagram devuelve `-1`) quedan como desconocidos, no como cero.

## Relevancia de cada post para el tópico

Que un creador sea relevante no hace relevantes todos sus posts: en "Agentes de IA" aparecían entre los destacados la noticia de un temblor, un Tesla y la promoción de eventos propios. Cada post se revisa con el LLM (`OPENAI_REVIEW_MODEL`, el mismo de la revisión de cuentas) contra el **tópico de la búsqueda** (sin tópico, los de la identidad usada); la identidad de la marca solo sirve de contexto para desempatar. Implementación en `backend/app/post_review.py`.

**El tópico es un paraguas, no una palabra clave.** Cuentan sus subtemas, herramientas, casos de uso y aplicaciones a cualquier dominio, sin que el post hable exclusivamente de él: para "inteligencia artificial", "IA aplicada a la contabilidad" o "ChatGPT para aprender inglés" son relevantes. Alta: el tópico o una aplicación suya es el eje del post; media: aparece de forma significativa o es un tema muy cercano; baja: mención de pasada o solo hashtags; ninguna: otro tema.

Por post devuelve: relevancia (alta, media, baja, ninguna), tipo de contenido (educativo, noticia, promoción o evento, venta, opinión, entretenimiento, personal, otro), 1–3 subtemas específicos (insumo para detectar tópicos en caliente) y si el texto no alcanza para saber de qué trata el video.

- **Solo los posts de relevancia alta o media cuentan para tendencias.** Los demás se muestran aparte, plegados.
- **La línea base del creador usa todos sus posts**, hablen de lo que hablen: mide lo que esa cuenta consigue normalmente, y quitar los de otros temas dejaría muestras demasiado chicas.
- **Orden con los reels:** primero se revisan con el caption; solo los relevantes o indeterminados (caption que es solo "comenta X") se transcriben, y con la transcripción se revisan de nuevo. Lo que está claramente fuera de tema no se transcribe.
- El veredicto se guarda por post y tópico (`post_topic_reviews`) y solo se vuelve a pedir si cambian el tópico, el caption, la transcripción o las instrucciones. Corre por tandas de 12 en cada consulta de la vista.

## Transcripción de reels

Para saber de qué habla un reel más allá del caption, se transcriben los primeros `TRANSCRIPT_MAX_SECONDS` (30 s) de su audio con OpenAI (`OPENAI_TRANSCRIBE_MODEL`, por defecto `gpt-4o-mini-transcribe`, ~$0,003/min). Solo se transcriben los reels que la revisión de relevancia marcó como relevantes o indeterminados. Todos con el mismo tramo inicial (gancho y planteamiento), así virales y normales se comparan igual. Aun transcribiendo los ~90 reels de una búsqueda serían como mucho 45 minutos: unos $0,15.

- **Cómo:** se descarga el MP4 del CDN de Instagram (6–35 MB; hasta 100 MB), se copia la pista de audio sin recodificar a un M4A (unos 200 KB por 30 s, con PyAV) y se envía a OpenAI. El video no se guarda; solo el texto (`instagram_posts.transcript`) y los segundos cubiertos.
- **Cuándo:** automáticamente cuando los posts están listos y revisados, por tandas de 6 en cada consulta de la vista (como la revisión LLM de cuentas). Cada reel se reserva antes de procesarlo para no pagarlo dos veces.
- **Caducidad:** los enlaces del CDN vencen (parámetro `oe`, ~1–2 días después de la recolección). Un enlace vencido se marca `expired` sin descargar; la vista muestra cuándo vence el primer enlace pendiente. Para recuperarlos hay que volver a recoger los posts.
- **Estados:** `ok`, `no_speech` (solo música), `no_audio`, `expired`, `too_large`, `unavailable` (sin enlace o el CDN lo niega) y `error`. Los fallos transitorios del proveedor (cuota, red) dejan el reel pendiente y se reintenta en la siguiente consulta.

## Métrica de relevancia

El número absoluto de likes no sirve para comparar: una cuenta de 2 millones siempre gana a una de 5 mil, y un post de hace 30 días siempre gana a uno de hace una hora. Por eso cada post se compara **con su propio creador** y **corrigiendo la edad**. Implementación en `backend/app/post_metrics.py` (funciones puras).

1. **Madurez por edad.** Un post acumula rápido al principio y luego se estanca. Se modela con `f(edad) = 1 − e^(−edad/τ)`, con τ = 48 h para video y 18 h para estáticos (≈95 % del total a 3τ). El valor observado se proyecta a su total esperado: `proyectado = observado / f(edad)`. La edad se mide en el momento de la observación. Un post con menos de 12 h es **provisional**: se puntúa con la madurez de 12 h, se marca y no entra en ninguna línea base.
2. **Línea base del creador.** Mediana de los valores proyectados de sus otros posts maduros del **mismo formato** (video o estático), excluyendo el propio post. Mediana y no promedio: un viral no infla la base. Si hay menos de 4 posts del formato, se usan todos los formatos y la confianza baja.
3. **Señales.** Sin vistas disponibles, se usan likes (la mejor aproximación al alcance) y comentarios (resonancia) **por separado**. Cada una da un múltiplo `(proyectado + 10) / (base + 10)`; la pseudo-cuenta de 10 evita que 2 likes frente a una base de 0 parezcan "el triple". El **rendimiento** es su media geométrica ponderada (likes 0,7; comentarios 0,3). ×1 es lo normal del creador; ×3 es el triple. Separarlas importa: si se sumaran, un post con 12 mil comentarios por un "comenta X y te lo envío" dominaría la suma; con la media geométrica un pico de ×100 en comentarios aporta ×4 (100^0,3).
4. **Rareza.** z robusto en escala logarítmica: `(log valor − mediana) / (1,4826 · MAD)`, con MAD mínimo de 0,15. Distingue un ×2 de un creador muy constante (raro) de un ×2 de un creador que siempre oscila (habitual).

| Etiqueta | Regla |
| --- | --- |
| Viral | rendimiento ≥ 3 y z ≥ 2 |
| Sobresaliente | rendimiento ≥ 1,5 y z ≥ 1 |
| Normal | entre 0,67 y lo anterior |
| Bajo | rendimiento < 0,67 |
| Sin línea base | menos de 4 posts maduros comparables |

**Confianza:** alta con ≥ 8 posts comparables por señal y ambas señales disponibles; media con 4–7 o una señal faltante; baja si el post es provisional, la base mezcla formatos, faltan los likes o la base de likes es menor que 10 (audiencia que casi no interactúa).

**Posible comment-bait:** se marca cuando los comentarios son al menos la mitad de los likes y suman 20 o más. Es el patrón de "comenta una palabra y te envío el recurso": tracción real, pero inducida por la llamada a la acción. La marca es informativa y no cambia la etiqueta.

**Velocidad:** con dos lecturas del mismo post separadas por 6 h o más se informan likes y comentarios ganados por hora. Es la señal de aceleración que no depende de las vistas. Todavía no puntúa: hace falta acumular lecturas (volviendo a recoger cada 24 h) para tener una línea base de velocidad por creador.

El engagement sobre seguidores se muestra para comparar creadores entre sí, pero **no puntúa**: seguidores no equivale a quién vio el post.

## Límites conocidos

- τ es un supuesto inicial. Con observaciones repetidas conviene ajustarlo por formato o por creador.
- 30 posts en 30 días puede ser poco para creadores que publican una vez por semana: su línea base tendrá confianza baja o no existirá.
- Un post en colaboración aparece en el perfil de cada coautor; se guarda una vez y queda asignado al último creador que lo trajo.
- Sin vistas no se distingue un post que llegó a mucha gente con pocos likes de uno que llegó a poca. Los likes son una aproximación, no el alcance.
- Hay cuentas grandes con likes casi nulos (audiencia inactiva o likes ocultos que llegan como 0). Su confianza queda en baja.
