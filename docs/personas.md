# Personas del paso 1

La interpretación v3 propone segmentos editoriales: rol, necesidad, objetivo, barreras por comprobar, ideas de contenido, pregunta de validación y referencias. Cada segmento indica si proviene de contexto declarado, señales textuales o una hipótesis exploratoria. No infiere edad, género, ingresos, ubicación de seguidores ni intención de compra a partir de contadores.

En la versión 3.1, «historia de la marca» y «planes para compartir» son ángulos editoriales: requieren expresiones concretas en el contexto del perfil/equipo o en varias piezas distintas. Palabras sueltas como «historia», «familia» o «compartir» no los activan. No se agregan automáticamente a los tópicos de búsqueda de la marca; se conservan si el equipo los declara expresamente. Las necesidades se redactan directamente, con su fundamento indicado por separado. La pantalla omite también el prefijo generado en registros anteriores y conserva el resumen de la muestra en el JSON exportable.

El motor sigue siendo local, por reglas y vocabulario ampliable; no ejecuta un LLM ni garantiza detectar todos los sectores. No se fuerza un número de segmentos cuando la evidencia no alcanza. Una bio que solo pide seguidores produce, como máximo, una persona exploratoria sobre la decisión de seguir la cuenta; no permite adivinar qué publica.

## Completar contexto sin otra extracción

En **Identidad de marca**, el formulario **Contexto del equipo** guarda qué publica la marca, la audiencia que quiere atender y temas específicos. El botón **Guardar contexto y generar personas** ejecuta `PUT /api/brands/{id}/context` con `description`, `audience` y `topics`.

Este endpoint valida y guarda el brief, omite contactos, reinterpreta observaciones ya guardadas y conserva tanto la identidad actual como las fechas y métricas originales. No consulta proveedores ni modelos. La propuesta se aplica expresamente con **Usar propuesta como borrador**; después se puede editar y confirmar. `role` y `need` mantienen el contrato que consume el paso 2, y los nuevos campos viajan en la identidad y el JSON del análisis sin migración de tablas.

Los temas específicos declarados de entretenimiento pueden generar un segmento para esa comunidad y uno exploratorio para quienes quieren descubrir el contenido. El nombre procede del contexto, no de una lista de franquicias codificada para una cuenta.

## Más datos útiles

- Cobertura: perfiles utilizables, textos distintos, piezas analizadas y vistas conocidas.
- Por red: cantidad de piezas únicas, formatos explícitos, publicación más reciente, mediana y enlaces con mayores vistas **solo de esa muestra**. Cero y desconocido se conservan como valores distintos. No se calcula engagement ni crecimiento a partir de una única observación.
- Acciones sugeridas y contexto pendiente para mejorar la lectura.
- TikTok: `account_details` guarda likes acumulados, cuentas seguidas y verificación cuando el proveedor los entrega. [Bright Data documenta esos campos públicos](https://brightdata.com/products/web-scraper/tiktok/profiles). No se convierten likes en vistas y no se agregan consultas pagas de publicaciones. Los resultados antiguos siguen mostrando desconocidos si no contenían esos campos.

Las observaciones y la interpretación se guardan separadas. Reinterpretar un perfil nunca se presenta como una nueva visita a la red social. Las propuestas deben contrastarse con respuestas o experimentos propios antes de tratarlas como información real de la audiencia.
