# Contrato paso 2 → paso 3 · v1.0

El equipo de descubrimiento implementa su propio módulo. No necesita modificar las rutas de identidad ni el frontend.

1. Obtener una marca con `GET /api/brands` o `GET /api/brands/{id}`. El objeto `identity` contiene audiencia, región, tópicos y personas confirmadas o en borrador.
2. Obtener piezas públicas por un método permitido. No usar sesiones de terceros, datos privados, autores/personas, comentarios ni técnicas incompatibles con las condiciones de la fuente.
3. Normalizar el lote al esquema `BatchCreate` y enviarlo con `Content-Type: application/json` a `POST /api/brands/{id}/trend-batches`.
4. La respuesta devuelve `{id, posts, deduplicated}`. Consultar `GET /api/brands/{id}/report?batch_id={id}` o abrir el lote en la interfaz.

Swagger en `http://localhost:8000/docs` y esquema en `http://localhost:8000/openapi.json`. La validación canónica está en `backend/app/schemas.py`. No agregar dependencias cruzadas al módulo de sus compañeros.

## Campos

| Campo | Regla |
| --- | --- |
| `schema_version` | `"1.0"` |
| `mode` | `"public"` o `"demo"`; no mezclar |
| `source` | Nombre de la integración/origen, 3–200 caracteres |
| `compliance_confirmed` | `true`; declaración del proveedor sobre origen, permiso y ausencia de datos personales |
| `posts` | 1–500 piezas; conjunto completo de esa consulta |
| `external_id` | ID de pieza, no ID de persona; único por plataforma dentro del lote |
| `platform` | `linkedin`, `instagram`, `tiktok`, `youtube` |
| `url` | HTTPS, dominio de la plataforma, ruta no vacía, sin credenciales, parámetros, fragmentos ni puertos especiales |
| `title` / `hook` | Título (3–300) y apertura pública (3–1000); sin datos personales |
| `topic` | Tópico canónico en minúsculas, 2–100 caracteres; usar la misma etiqueta para el mismo tema |
| `format` | `video`, `short`, `carousel`, `text`, `article` |
| `published_at` | ISO 8601 con zona horaria; anterior o igual a las observaciones |
| `snapshots` | 1–60 observaciones `{observed_at, views}` en orden cronológico estricto; vistas acumuladas enteras no decrecientes y >= 0 |
| `source_method` | `official_api`, `open_dataset`, `manual_public`; `demo` solo en lotes demo |
| `source_reference` | Procedencia trazable: dataset, endpoint autorizado, fecha/contexto manual; 5–1000 caracteres, sin claves ni datos personales |

No enviar campos desconocidos: el contrato los rechaza (422). Las URLs se validan, **no se visitan**. Validarlas no verifica permiso, existencia ni exactitud. Las fechas deben incluir `Z` o un offset (`-05:00`); se rechazan observaciones futuras (salvo tolerancia de reloj de cinco minutos). La API no sintetiza fechas ni métricas ausentes.

El ejemplo [example-batch.demo.json](example-batch.demo.json) es sintético y sus enlaces no existen. Sus fechas son fijas para explicar el contrato; pueden quedar fuera de la ventana. Para una demo con fechas actuales, usar `POST /api/demo` o el botón de la interfaz. Nunca cambiarle `mode` para presentarlo como observado.

```powershell
$brandId = 'ID_DE_MARCA'
$body = Get-Content docs/example-batch.demo.json -Raw
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/brands/$brandId/trend-batches" -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

## Cálculos y manejo de datos faltantes

- **Velocidad:** `(vistas_actuales - vistas_anteriores) / días_transcurridos`. Los intervalos pueden tener duraciones distintas.
- **Aceleración:** `(velocidad_reciente / velocidad_previa - 1) * 100`. Se requieren 3 observaciones y velocidad previa positiva. Si falta evidencia o la base es cero: `null`, no 0% ni infinito.
- **Tópico:** mediana de aceleraciones disponibles. La pieza principal tiene el mayor número de vistas acumuladas dentro del tópico y filtros, no necesariamente la mayor aceleración.
- **Afinidad:** máxima similitud Jaccard entre tokens del tópico del lote y cada tópico de la marca; se ignoran tildes y algunas palabras vacías. No es relevancia semántica ni usa un LLM.
- **Score:** `0.45*afinidad + 35*clip(aceleracion/200,0,1) + 20*min(piezas/3,1)*min(series_comparables/3,1)`.
- **Estado:** ≥25% en aceleración; entre -10% y 25% estable; <-10% desacelerando; sin base comparable, sin serie suficiente.
- **Confianza:** media solo si hay al menos 3 piezas y 3 series comparables; en otro caso baja. No se afirma confianza alta ni representatividad de la red. No distingue autores.
- **Ventana:** incluye piezas cuya última observación cae dentro de los últimos N días. No obliga a que los dos intervalos completos estén contenidos en esa ventana. No se mezclan lotes ni se comparan vistas absolutas para rankear formatos entre plataformas.

## Persistencia e idempotencia

Se conserva cada lote completo. Misma marca + mismo JSON canónico devuelve el ID existente con `deduplicated: true`. El orden de las claves no importa; el orden del arreglo de piezas sí importa. La fecha de importación no convierte un lote viejo en evidencia fresca. No hay fusión entre lotes; incluir el historial en `snapshots` en cada entrega.

El informe sin `batch_id` selecciona el lote **público** importado más recientemente. La demo solo aparece si se selecciona expresamente. Un lote de otra marca responde 404. Es aislamiento de consulta, no control de acceso: la API local todavía no tiene usuarios ni autenticación.

## Reparto recomendado

- Persona 1: identidad y motor de priorización (`app/services.py`, rutas y React).
- Compañeros paso 2: adaptadores/fuentes autorizadas + normalización de `BatchCreate`.
- Integración: una prueba compartida con un lote real pequeño y evidencia del permiso de uso. Antes de hacer afirmaciones semanales, recopilar series reales y revisar cobertura, duplicados y sesgos de selección.
