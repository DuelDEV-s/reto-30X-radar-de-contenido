# Validación local · 17 de octubre de 2026

## Corrección: diagnóstico de inicio Bright Data

- Los errores HTTP de validación y scraper inexistente se distinguen de fallos de conexión, timeout y respuestas sin snapshot. Se conserva un código seguro y no se guardan mensajes externos en bruto.
- Timeout de inicio ampliado de 8 a 25 segundos; límite por perfil 55 segundos y proxy 180 segundos.
- 68 pruebas de backend aprobadas, incluidas pruebas sintéticas para cada diagnóstico, persistencia del código, ausencia de reenvío y compatibilidad con intentos antiguos sin causa guardada. Docker reconstruido y API saludable.
- Comprobación de lectura desde Docker: el backend recibió la clave, la API respondió HTTP 200 y ambos IDs configurados aparecieron en el catálogo. La consulta inicial de snapshots de Instagram no devolvió ejecuciones. Tras autorización explícita se realizó una única recolección del perfil que falló: Bright Data entregó snapshot, el trabajo terminó y se guardó el perfil normalizado con contadores reales. No hubo reintentos de POST. La causa exacta del intento antiguo sigue sin poder reconstruirse porque no conservó el diagnóstico.

## Actualización: Bright Data principal

- 58 pruebas de backend aprobadas: proveedores principal y de respaldo, trabajos pendientes/fallidos, respuestas privadas rechazadas, timeout ambiguo sin reenvío, límite de trabajos, persistencia entre sesiones y protección de identidad.
- Compilación React/TypeScript y reconstrucción Docker aprobadas. PostgreSQL en revisión 003; `alembic check` sin diferencias.
- Consulta desde la interfaz contra Docker de la marca QA existente: identifica Bright Data y cada API de respaldo como pendientes de configuración, sin inventar métricas. La marca real del usuario se conserva.
- Las pruebas con respuestas de proveedores usan fixtures sintéticos. No se hicieron colecciones de pago ni se verificó acceso real sin las credenciales del equipo.

## Verificación anterior: análisis automático de perfiles

- 30 pruebas de backend aprobadas, incluidas respuestas sintéticas de YouTube e Instagram, estados sin credenciales, fallos de proveedores, contadores ausentes, reutilización de consultas y conservación de identidad confirmada.
- Compilación de React y reconstrucción del entorno Docker aprobadas. Migración 002 aplicada en PostgreSQL; `alembic check` sin diferencias.
- Creación desde navegador con solo nombre y dos enlaces probada contra Docker. Sin claves configuradas, el resultado identifica ambas fuentes como pendientes y conserva métricas ausentes en lugar de generar datos.
- No se han verificado consultas en vivo a los perfiles del equipo: no se proporcionaron credenciales. Los casos con datos extraídos en las pruebas son fixtures sintéticos.

## Base inicial

Comprobado en Windows con Node 24, Python 3.12 y Docker Desktop (motor Linux):

- 14 pruebas API/cálculo aprobadas con `python -m pytest -q`. Un aviso de deprecación de la dependencia AnyIO/Starlette, sin fallo de pruebas.
- Compilación de React/TypeScript aprobada con `npm run build`.
- `docker compose config --quiet` válido.
- Construcción de las dos imágenes y arranque completo con `docker compose up --build -d` aprobados.
- PostgreSQL y API saludables; interfaz servida por Nginx en el puerto 5173.
- PostgreSQL con revisión Alembic `001`; `alembic check` sin diferencias entre esquema y modelos.
- Demo creada y consultada desde el navegador contra la API Docker y PostgreSQL: 18 piezas, seis tópicos, aceleración máxima sintética 210%.
- Interfaz: creación de marca, confirmación de identidad, rechazo de JSON mal formado, importación de un lote demo y apertura del detalle probados en navegador durante la revisión local.
- Filtro TikTok con resultado vacío cuando la muestra no contiene esa plataforma.
- Comprobada la adaptación del DOM a 390 px, sin desbordamiento horizontal. La herramienta de captura móvil no produjo una imagen fiable; no se entrega como evidencia visual.
- Revisado el diseño de escritorio y capturada una vista del entorno Docker.
- Consola de navegador sin errores en la comprobación final.

El primer arranque encontró un rechazo de Windows al publicar PostgreSQL en 5432; se usa `POSTGRES_PORT=15432` por defecto, manteniendo 5432 dentro de la red Docker. El puerto es configurable.

En la verificación inicial no se probaron fuentes reales, extracción de redes, modelos de IA/JEV, permisos de una fuente externa ni rendimiento editorial. Los conectores de perfiles añadidos después están descritos arriba; IA/JEV y el descubrimiento del paso 2 siguen pendientes. La demo es sintética. La CI queda definida en `.github/workflows/ci.yml`; su ejecución remota requiere subir la rama y no se considera realizada por estas comprobaciones locales.
