# Paso 3 · Informe editorial

El radar une los resultados del paso 2 con la identidad utilizada en cada corrida. La pantalla principal permite elegir una fuente guardada, priorizar temas, revisar evolución y piezas, y preparar un brief para producir una prueba de contenido.

## Flujo

1. Crear o seleccionar una marca y revisar su identidad en el paso 1.
2. Ejecutar el descubrimiento en la red elegida y completar sus revisiones. En Instagram/TikTok hacen falta publicaciones, líneas base y veredictos temáticos; la agrupación semántica guardada mejora la presentación. Si no existe, se muestran las etiquetas exactas como agrupación provisional.
3. Pulsar **Ver informe editorial** o abrir **Radar de contenido** y elegir la corrida.
4. Seleccionar un tema para ver por qué considerarlo, su encaje con la marca, series, evidencia y propuestas. **Copiar brief** y **Descargar** exportan el tema seleccionado; el método y las limitaciones se incluyen.
5. En **Cobertura, límites y método**, inspeccionar la metodología y exportar el contrato JSON completo.

Fuente, tema, búsqueda, red y marca se conservan en la URL. El enlace funciona contra la misma instancia y base de datos; no publica el informe. Los lotes v1 siguen disponibles en **Ver lotes**.

**Fuentes e integración** reúne las corridas de ambos motores y los lotes de la marca, con filtros de red/origen, estado guardado y acceso al informe. Muestra aparte la configuración de conectores de perfiles (paso 1) y del radar LinkedIn/YouTube (paso 2). La presencia de credenciales no confirma permisos, cuota o acceso en vivo. La importación manual de JSON está en **Importar un lote externo**, como opción avanzada. La pestaña seleccionada también se conserva al recargar.

## Lecturas sin gasto de proveedores

- `GET /api/brands/{id}/editorial-sources`
- `GET /api/brands/{id}/editorial-report?source=creator:{run_id}`
- También admite `trend:{run_id}` y `batch:{batch_id}`.

Estas rutas solo leen la base. No ejecutan búsqueda, recolección, transcripción, agrupación ni modelos. Actualizar el informe vuelve a leer lo guardado. Las rutas de avance del paso 2 mantienen su funcionamiento previo, que puede procesar tandas con proveedores configurados.

No se mezclan motores, corridas ni modos demo/público en un ranking. La fuente debe pertenecer a la marca. La identidad del motor LinkedIn/YouTube se adapta desde su contrato `BrandIdentity`; si la marca cambió, la pantalla lo indica y conserva el contexto de la corrida.

## Qué significa cada gráfico

| Fuente | Serie temporal | Prioridad |
| --- | --- | --- |
| Creadores Instagram/TikTok | Cantidad de piezas temáticas de la muestra por semana | Regla sobre 100: 50 por tracción logarítmica, 25 por momentum acotado, 25 por soporte de cuentas y piezas. Ver fórmula en `app/editorial.py` |
| LinkedIn | Publicaciones encontradas en el índice de búsqueda por semana | `opportunity_score` del paso 2 × 100 |
| YouTube | Índice de atención del paso 2, separado de LinkedIn | `opportunity_score` del paso 2 × 100 |
| Lote v1 | Vistas acumuladas de la pieza de referencia en fechas observadas | `score-v1` original, con su método visible |

Tracción 1× significa rendimiento habitual del creador. Momentum usa cambios logarítmicos; no se presenta como un porcentaje de crecimiento. LinkedIn no tiene vistas observadas en el índice. Ausencias se muestran como N/D. La prioridad y la confianza no son probabilidades de éxito. Los patrones de producción comparan frecuencias cuando existe grupo de control; no prueban causalidad.

Los gráficos usan Recharts/SVG; los valores temporales tienen una tabla alternativa y el ranking tiene valores visibles en la lista. Motion limita las transiciones al cambio de estado y respeta `prefers-reduced-motion`. La vista editorial y las bibliotecas gráficas se cargan en módulos separados.

## Previews

No se descarga ni se almacena video para estas previews. Se construyen URLs de reproductores a partir de hosts e identificadores públicos admitidos; no se inserta HTML del proveedor. Antes de pulsar **Ver la pieza** no se carga ningún iframe de terceros.

- YouTube: reproductor `youtube-nocookie.com` para video o short con ID válido. [Documentación oficial](https://developers.google.com/youtube/player_parameters).
- TikTok: reproductor oficial `tiktok.com/player/v1/{id}`. [Documentación oficial](https://developers.tiktok.com/doc/embed-player).
- Instagram: embed de `/reel/` o `/p/`.
- LinkedIn: embed de posts con identificador de actividad. Los artículos o enlaces sin ID quedan como enlace original.

La plataforma puede bloquear un embed o exigir cookies/login. La aplicación conserva el enlace original y permite cerrar el reproductor; no intenta sortear esa restricción. Las piezas demo no generan enlaces ni embeds ficticios.

## Comprobación sin claves

**Explorar demo** crea 18 piezas sintéticas para comprobar rankings, gráficos, filtros, exportación y adaptación. Los tests también recorren los dos motores con publicaciones y reportes guardados sintéticos, validan el contexto congelado y comprueban que las lecturas no escriban ni llamen a proveedores.
