import { lazy, Suspense, useState } from "react";
import type { ReactNode } from "react";
import { ArrowUpRight, ChevronLeft, ChevronRight, Grid2X2, ListFilter, Search, Table2 } from "lucide-react";
import type { CreatorPost, RunPosts } from "./types";
import { filterPosts, metric, POST_LABELS, relative, shortDate } from "./discoveryData";
import MediaPreview from "./MediaPreview";

const ContentMetrics = lazy(()=>import("./DiscoveryCharts").then(m=>({default:m.ContentMetrics})));
const FORMATS: Record<string,string> = {reel:"Reel",video:"Video",carousel:"Carrusel",image:"Imagen",unknown:"Sin confirmar"};
const PAGE_SIZE = 12;

export default function DiscoveryContentResults({data,creator,onCreator,renderTable}: {
  data:RunPosts;creator:string;onCreator:(value:string)=>void;renderTable:(items:CreatorPost[])=>ReactNode;
}) {
  const [view,setView]=useState<"cards"|"table">("cards");
  const [search,setSearch]=useState(""),[label,setLabel]=useState(""),[format,setFormat]=useState("");
  const [onlyTopic,setOnlyTopic]=useState(true),[sort,setSort]=useState<"performance"|"views"|"recent">("performance");
  const [page,setPage]=useState(0);
  const shown=filterPosts(data.items,{creator,search,label,format,onlyTopic,sort});
  const pages=Math.ceil(shown.length/PAGE_SIZE), current=Math.min(page,Math.max(pages-1,0));
  const visible=shown.slice(current*PAGE_SIZE,(current+1)*PAGE_SIZE);
  const reset=()=>{setSearch("");setLabel("");setFormat("");onCreator("");setOnlyTopic(true);setSort("performance");setPage(0);};
  const filtered=!!(search||label||format||creator||!onlyTopic);
  return <div className="ds-content-results">
    <Suspense fallback={<div className="ds-skeleton" role="status">Preparando la lectura visual de la muestra…</div>}><ContentMetrics items={data.items} selectedLabel={label} onLabel={value=>{setLabel(label===value?"":value);setPage(0);}}/></Suspense>
    <div className="ds-section-heading ds-gallery-heading"><div><span className="eyebrow">BIBLIOTECA DE EVIDENCIA</span><h3>Explora las piezas, no solo los números.</h3><p>{shown.length} de {data.items.length} publicaciones · {onlyTopic ? "incluye pendientes de revisión" : "incluye piezas fuera del tema"}</p></div>
      <div className="ds-view-switch" role="group" aria-label="Vista de publicaciones"><button aria-pressed={view==="cards"} onClick={()=>setView("cards")}><Grid2X2 size={15}/> Tarjetas</button><button aria-pressed={view==="table"} onClick={()=>setView("table")}><Table2 size={15}/> Tabla</button></div>
    </div>
    <div className="ds-filters" aria-label="Filtros de publicaciones">
      <label className="ds-search"><span><Search size={14}/> Buscar una pieza</span><input value={search} onChange={e=>{setSearch(e.target.value);setPage(0);}} placeholder="Texto, creador o subtema"/></label>
      <label>Creador<select aria-label="Creador" value={creator} onChange={e=>{onCreator(e.target.value);setPage(0);}}><option value="">Todos los creadores</option>{data.creators.map(c=><option key={c.username} value={c.username}>@{c.username}</option>)}</select></label>
      <label>Rendimiento<select aria-label="Rendimiento" value={label} onChange={e=>{setLabel(e.target.value);setPage(0);}}><option value="">Todas las categorías</option>{Object.entries(POST_LABELS).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></label>
      <label>Formato<select aria-label="Formato" value={format} onChange={e=>{setFormat(e.target.value);setPage(0);}}><option value="">Todos los formatos</option>{Object.entries(FORMATS).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></label>
      <label>Ordenar por<select aria-label="Ordenar por" value={sort} onChange={e=>{setSort(e.target.value as typeof sort);setPage(0);}}><option value="performance">Rendimiento relativo</option><option value="views">Vistas observadas</option><option value="recent">Más recientes</option></select></label>
    </div>
    <div className="ds-filter-summary"><label><input type="checkbox" checked={onlyTopic} onChange={e=>{setOnlyTopic(e.target.checked);setPage(0);}}/> Ocultar las piezas descartadas por tema</label>{filtered && <button className="text-button" onClick={reset}><ListFilter size={13}/> Limpiar filtros</button>}</div>
    {!shown.length ? <div className="ds-empty"><Search size={24}/><h4>No hay piezas con estos filtros.</h4><p>Prueba otro creador, categoría o texto de búsqueda.</p><button className="button" onClick={reset}>Restablecer filtros</button></div>
      : view==="table" ? <div className="pipeline-table-wrap ds-detail-table">{renderTable(visible)}</div>
      : <div className="ds-content-grid">{visible.map(p=><ContentCard key={p.shortcode} post={p}/>)}</div>}
    {pages>1 && <nav className="ds-pagination" aria-label="Páginas de publicaciones"><span>{current*PAGE_SIZE+1}–{Math.min((current+1)*PAGE_SIZE,shown.length)} de {shown.length}</span><div><button className="button small" disabled={current===0} onClick={()=>setPage(current-1)}><ChevronLeft size={15}/> Anterior</button><span aria-live="polite">{current+1} / {pages}</span><button className="button small" disabled={current>=pages-1} onClick={()=>setPage(current+1)}>Siguiente <ChevronRight size={15}/></button></div></nav>}
  </div>;
}

function ContentCard({post:p}: {post:CreatorPost}) {
  return <article className={`ds-content-card performance-${p.label}`}>
    <header><a href={p.url} target="_blank" rel="noopener noreferrer">@{p.username}<ArrowUpRight size={13}/></a><span>{FORMATS[p.content_type]}</span></header>
    <MediaPreview url={p.url} title={p.caption||p.shortcode} thumbnailUrl={p.thumbnail_url} compact/>
    <div className="ds-content-copy"><div className="ds-performance"><span className={`post-label ${p.label}`}>{POST_LABELS[p.label]}</span><strong>{relative(p.performance)}</strong></div><small className="ds-base-note">Frente a la base del mismo creador{p.provisional ? " · provisional" : ""}</small>
      <p className="ds-caption">{p.caption||"La fuente no incluyó texto para esta publicación."}</p>
      <div className="ds-content-metrics"><div><small>Vistas</small><strong>{metric(p.views)}</strong></div><div><small>Me gusta</small><strong>{metric(p.likes)}</strong></div><div><small>Comentarios</small><strong>{metric(p.comments)}</strong></div></div>
      <div className="ds-post-topics">{p.topic_review ? <span className={p.topic_review.on_topic ? "ds-relevant" : "ds-excluded"}>{p.topic_review.on_topic ? `Relevancia ${p.topic_review.relevance}` : "Fuera del tema"}</span> : <span>Revisión pendiente</span>}{(p.topic_review?.subtopics||[]).slice(0,2).map(t=><span key={t}>{t}</span>)}</div>
      <details className="ds-card-details"><summary>Por qué se incluye y más datos</summary><p>{p.topic_review?.reason||"Esta pieza aún no tiene veredicto de relevancia. Su presencia no equivale a una aprobación."}</p><dl><div><dt>Confianza del cálculo</dt><dd>{p.confidence}</dd></div><div><dt>Compartidos</dt><dd>{metric(p.shares)}</dd></div><div><dt>Base de comparación</dt><dd>{p.baseline_scope==="formato" ? "Mismo formato" : "Formatos combinados"}</dd></div></dl>{p.caption && <><strong>Texto de la pieza</strong><p>{p.caption}</p></>}{p.comment_bait && <p>La llamada a comentar puede influir en el contador de comentarios.</p>}{p.transcript && <><strong>Transcripción · {p.transcript_seconds??"N/D"} s</strong><p>{p.transcript}</p></>}</details>
      <footer><time dateTime={p.posted_at}>{shortDate(p.posted_at)}</time>{p.is_paid_partnership && <span>Patrocinado</span>}<a href={p.url} target="_blank" rel="noopener noreferrer">Ver original <ArrowUpRight size={12}/></a></footer>
    </div>
  </article>;
}
