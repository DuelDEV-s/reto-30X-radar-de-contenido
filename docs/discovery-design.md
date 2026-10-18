# Lectura visual del paso 2

La consulta conserva los motores, endpoints, estados y revisiones existentes. La presentación añade una biblioteca de evidencia con tarjetas/tabla, filtros por texto, creador, clasificación y formato, orden por rendimiento/vistas/fecha y páginas de 12 piezas. Un post sin revisión permanece visible y se identifica como pendiente; solo los descartados explícitos se ocultan con el filtro de tema. Los filtros son locales al resultado y se reinician al cambiar de corrida. La red continúa en el almacenamiento local y la pestaña principal en la URL existente.

## Contrato visual y técnico

- React controla los filtros, selecciones, paginación, tarjetas y detalles; Recharts/SVG dibuja las barras semanales y series de tendencias. No hay canvas, imágenes generadas ni llamadas de proveedores nuevas. `DiscoveryCharts` se carga bajo demanda.
- Resumen de contenido: número de piezas y creadores, comparables, piezas por encima de 1× y mediana de rendimiento. Los desconocidos no se convierten en cero. La distribución por clasificación utiliza barras con conteos visibles y botones accesibles; conserva las etiquetas del motor, incluida «Viral».
- Evolución: publicaciones recogidas por semana UTC. Los ceros significan que la muestra no contiene piezas en ese intervalo, no ausencia de publicaciones en la plataforma. Incluye tabla alternativa y no suaviza la trayectoria.
- LinkedIn/YouTube: un selector de tema coordina ranking y series. LinkedIn conserva posts del índice; YouTube conserva el índice de atención del motor. Son paneles separados con sus propias unidades y tablas. Prioridad/confianza no se presentan como probabilidades.
- Mapa de creadores: conserva la tracción logarítmica, amplitud y momentum del motor. Una pieza sin momentum no se coloca artificialmente en cero. Los temas omitidos del mapa siguen en el selector/matriz. Se puede seleccionar con teclado y desde el selector, sin depender del hover.
- Medios: usa el componente común de miniaturas/reproductores sin autoplay. En cada página hay como máximo 12 tarjetas. Las imágenes e iframes siguen usando carga diferida. Los resultados, subtemas y patrones también permiten abrir las referencias originales.
- Color: verde para foco y rendimiento sobre la base, azul para la serie de publicaciones en LinkedIn, ámbar para categorías bajas/advertencias y gris para contexto/desconocidos. Los nombres y valores acompañan al color.

## Móvil y accesibilidad

Objetivo: retrato de 390 × 844 y escritorio. Métricas en dos columnas, gráficas y tarjetas en una columna, controles secundarios compactos, navegación de etapas desplazable y tablas/mapa ancho con scroll propio. Los campos permanecen en el flujo y no hay overlays que oculten la acción al abrir el teclado. Los selectores, botones y categorías tienen estado accesible; los controles principales alcanzan 44 px en móvil. Los movimientos de entrada y hover se desactivan con `prefers-reduced-motion`. La información esencial permanece disponible sin animación, hover o servicios adicionales.

Las métricas cargadas permanecen visibles durante la exploración local; filtrar o cambiar de tabla a tarjetas no vuelve a consultar proveedores. El polling del motor conserva su comportamiento previo. La verificación visual usa datos sintéticos aislados, identificados como tales, y nunca los agrega a PostgreSQL.

## Validación

`npm test` valida mediana, desconocidos/cero, agregación UTC, rangos amplios, filtros, revisión pendiente y orden sin mutar datos originales. `npm run build` verifica TypeScript y la producción. La QA visual cubre galería/tabla, filtros sin resultados, cambio de categoría/tema, matriz/mapa, enlaces y miniaturas, estados vacíos y movimiento reducido. Las capturas de prueba indican su origen sintético.
