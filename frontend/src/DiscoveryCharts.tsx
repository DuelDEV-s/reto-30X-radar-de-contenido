import { useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, LabelList, Area, AreaChart } from "recharts";
import type { CreatorPost, PostLabel, TrendTopic } from "./types";
import { metric, postSummary, relative, shortDate, weeklyPosts } from "./discoveryData";

const axis = {fontSize:11, fill:"#687769"};
const tooltip = {border:"1px solid #dce5d6",borderRadius:12,fontSize:12,boxShadow:"0 8px 24px #14291a12"};

export function ContentMetrics({items, selectedLabel, onLabel}: {items:CreatorPost[];selectedLabel:string;onLabel:(label:PostLabel)=>void}) {
  const s = postSummary(items), weeks = weeklyPosts(items);
  return <section className="ds-results-overview" aria-label="Resumen de publicaciones de la consulta">
    <div className="ds-section-heading"><div><span className="eyebrow">LECTURA DE LA MUESTRA</span><h3>Qué destaca en esta consulta.</h3></div><span className="ds-scope">{s.pieces} piezas recogidas · sin filtros</span></div>
    <div className="ds-metrics">
      <article><small>Publicaciones</small><strong>{metric(s.pieces)}</strong><span>Recogidas en esta consulta</span></article>
      <article><small>Creadores</small><strong>{metric(s.creators)}</strong><span>Con publicaciones disponibles</span></article>
      <article><small>Sobre su propia base</small><strong>{s.above}<em> / {s.comparable}</em></strong><span>Piezas con rendimiento mayor que 1×</span></article>
      <article><small>Rendimiento mediano</small><strong>{relative(s.median)}</strong><span>Entre las {s.comparable} piezas comparables</span></article>
    </div>
    <div className="ds-chart-grid">
      <article className="ds-chart-card"><h4>Cómo se reparte el rendimiento</h4><p>Pulsa una categoría para explorar sus piezas.</p>
        <div className="ds-distribution">{s.buckets.map(b => <button key={b.label} aria-pressed={selectedLabel === b.label} onClick={() => onLabel(b.label)} className={selectedLabel === b.label ? "selected" : ""}>
          <span>{b.name}</span><i><b style={{width:`${Math.max(...s.buckets.map(x=>x.count),1) ? b.count / Math.max(...s.buckets.map(x=>x.count),1) * 100 : 0}%`,background:b.color}} /></i><strong>{b.count}</strong>
        </button>)}</div>
      </article>
      <article className="ds-chart-card"><h4>Cuándo se publicaron</h4><p>Piezas de la muestra por semana · fechas UTC.</p>
        <div className="ds-chart" role="img" aria-label={`Publicaciones por semana: ${weeks.map(w=>`${shortDate(w.date)}: ${w.posts}`).join("; ")}`}>
          <ResponsiveContainer width="100%" height="100%"><BarChart data={weeks} margin={{top:22,right:14,left:-20,bottom:0}} accessibilityLayer>
            <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="#e8ede3"/><XAxis dataKey="date" tickFormatter={shortDate} tick={axis} axisLine={false} tickLine={false} minTickGap={18}/><YAxis allowDecimals={false} tick={axis} axisLine={false} tickLine={false}/><Tooltip labelFormatter={v=>`Semana del ${shortDate(String(v))}`} contentStyle={tooltip} formatter={v=>[v,"Publicaciones"]}/><Bar dataKey="posts" fill="#71935d" radius={[5,5,0,0]} maxBarSize={48} isAnimationActive={false}><LabelList dataKey="posts" position="top" style={{fontSize:11,fill:"#3c5c38"}}/></Bar>
          </BarChart></ResponsiveContainer>
        </div>
        <details className="ds-chart-data"><summary>Ver datos de la gráfica</summary><table><thead><tr><th>Semana del</th><th>Piezas</th></tr></thead><tbody>{weeks.map(w=><tr key={w.date}><td>{shortDate(w.date)}</td><td>{w.posts}</td></tr>)}</tbody></table></details>
      </article>
    </div><p className="ds-chart-note">1× equivale a la base del mismo creador. Esta distribución describe la muestra, no toda la plataforma. La categoría «Viral» conserva la clasificación del motor.</p>
  </section>;
}

export function TrendComparison({topics, mode}: {topics:TrendTopic[];mode:"both"|"linkedin"|"youtube"}) {
  const [selected, setSelected] = useState("");
  const topic = topics.find(t=>t.topic_id === selected) || topics[0];
  if (!topic) return null;
  const li = topic.linkedin.timeseries.map(p=>({date:p.week,value:p.posts}));
  const yt = topic.demand.timeseries.map(p=>({date:p.week,value:p.attention}));
  return <section className="panel ds-topic-explorer" aria-label="Explorador visual de tendencias">
    <div className="ds-section-heading"><div><span className="eyebrow">EXPLORA LA SEÑAL</span><h3>Prioridad y evolución por tema.</h3><p>Selecciona un tema para inspeccionar su muestra.</p></div><span className="ds-scope">Prioridad del motor · 0 a 100</span></div>
    <div className="ds-topic-layout"><div className="ds-topic-ranking">{[...topics].sort((a,b)=>b.opportunity_score-a.opportunity_score).map(t=><button key={t.topic_id} onClick={()=>setSelected(t.topic_id)} aria-pressed={topic.topic_id===t.topic_id} className={topic.topic_id===t.topic_id ? "selected" : ""}><span>{t.label}</span><strong>{Math.round(t.opportunity_score*100)}<small> /100</small></strong><i><b style={{width:`${Math.max(0,Math.min(100,t.opportunity_score*100))}%`}}/></i></button>)}</div>
    <div className="ds-topic-series"><h4>{topic.label}</h4><div className="ds-chart-grid">
      {mode!=="youtube" && <Series data={li} title="Publicaciones en LinkedIn" unit="Posts en el índice" color="#3c6f9c"/>}
      {mode!=="linkedin" && <Series data={yt} title="Atención en YouTube" unit="Índice de atención del motor" color="#65894d"/>}
    </div><p className="ds-chart-note">Las gráficas conservan sus propias unidades. La prioridad y la confianza del motor no son probabilidades de éxito.</p></div></div>
  </section>;
}

function Series({data,title,unit,color}: {data:{date:string;value:number}[];title:string;unit:string;color:string}) {
  const known = data.filter(d=>Number.isFinite(d.value));
  return <article className="ds-chart-card"><h4>{title}</h4><p>{unit}</p>{known.length ? <>
    <div className="ds-chart" role="img" aria-label={`${title}: ${known.map(d=>`${shortDate(d.date)}: ${d.value}`).join("; ")}`}><ResponsiveContainer width="100%" height="100%"><AreaChart data={known} margin={{top:10,right:14,left:-10,bottom:0}} accessibilityLayer><CartesianGrid strokeDasharray="3 4" vertical={false} stroke="#e8ede3"/><XAxis dataKey="date" tickFormatter={shortDate} minTickGap={22} tick={axis} axisLine={false} tickLine={false}/><YAxis tick={axis} tickFormatter={v=>metric(Number(v))} axisLine={false} tickLine={false}/><Tooltip labelFormatter={v=>shortDate(String(v))} contentStyle={tooltip} formatter={v=>[v,unit]}/><Area type="linear" dataKey="value" stroke={color} fill={color} fillOpacity={0.09} strokeWidth={2.5} dot={{r:3,fill:color,strokeWidth:0}} isAnimationActive={false}/></AreaChart></ResponsiveContainer></div>
    <details className="ds-chart-data"><summary>Ver valores</summary><table><thead><tr><th>Semana</th><th>{unit}</th></tr></thead><tbody>{known.map(d=><tr key={d.date}><td>{shortDate(d.date)}</td><td>{d.value.toLocaleString("es")}</td></tr>)}</tbody></table></details>
  </> : <p className="ds-empty">No hay observaciones para esta serie.</p>}</article>;
}
