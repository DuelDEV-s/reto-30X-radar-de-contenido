import { useState } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import type { PatternTrait, RunPatterns, RunTrends, TrendState, InstagramTrendTopic } from "./types";

export const trendStates: Record<TrendState, string> = {
  en_caliente: "En caliente",
  emergente: "Emergente",
  en_ascenso: "En ascenso",
  consolidado: "Consolidado",
  estable: "Estable",
  saturado: "Saturado",
  enfriandose: "Enfriándose",
  insuficiente: "Poca evidencia",
  otros: "Otros",
};
const stateNotes: Record<TrendState, string> = {
  en_caliente: "Rinde muy por encima de lo normal, lo publican varios creadores y sigue acelerando.",
  emergente: "Nuevo en la última quincena y con rendimiento alto. Señal temprana: poca evidencia.",
  en_ascenso: "Gana adopción rápido con rendimiento al menos normal.",
  consolidado: "Rinde bien de forma sostenida, sin aceleración.",
  estable: "Rendimiento cercano a lo normal de los creadores.",
  saturado: "Mucho volumen y rendimiento por debajo de lo normal.",
  enfriandose: "Pierde adopción o rendimiento frente a la quincena anterior.",
  insuficiente: "Menos de 3 posts: no alcanza para concluir.",
  otros: "Subtemas sueltos que no forman un tópico.",
};
const ACTIONABLE = new Set<TrendState>(["en_caliente", "emergente", "en_ascenso"]);
// Divergente alrededor de ×1 (lo normal del creador): azul por encima, rojo por debajo, gris neutro en el medio.
const NEUTRAL = [240, 239, 236];
const ABOVE = [24, 79, 149];
const BELOW = [227, 73, 72];
const ACCENT = "#2a78d6";
const MUTED = "#c3c2b7";

const ratio = (v: number | null) => (v === null ? "—" : `×${v.toFixed(v >= 10 ? 0 : 2)}`);
const signed = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`);
const weekLabel = (iso: string) => new Date(iso).toLocaleDateString("es", { day: "numeric", month: "short" });

function cellColor(performance: number | null) {
  if (performance === null) return null;
  // log2 recortado a ±2: ×4 o más es el extremo azul, ×0,25 o menos el rojo.
  const t = Math.max(-1, Math.min(1, Math.log2(performance) / 2));
  const end = t >= 0 ? ABOVE : BELOW;
  const rgb = NEUTRAL.map((c, i) => Math.round(c + (end[i] - c) * Math.abs(t)));
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  return { background: `rgb(${rgb.join(",")})`, color: luminance < 0.55 ? "#fff" : "#0b0b0b" };
}

export function TrendsStep({ data }: { data: RunTrends | null }) {
  const [selected, setSelected] = useState("");
  if (!data) return <p className="muted"><LoaderCircle size={12} className="spin" /> Cargando tendencias…</p>;
  const topics = data.topics.filter((t) => t.state !== "otros");
  const current = topics.find((t) => t.name === selected);
  return (
    <>
      <h3>7 · Tendencias de «{data.topic}»</h3>
      <p className="muted">
        Solo cuentan los posts sobre el tópico. Los subtemas de cada post se agrupan en tópicos y cada tópico se mide por su
        tracción (cuánto hace rendir a los creadores frente a su propia normalidad, pesando más lo reciente), su amplitud
        (cuántos creadores lo publicaron en los últimos 14 días) y su momentum (los últimos 14 días frente a los 14 anteriores).
      </p>
      {data.state === "waiting" && (
        <p className="profile-message">
          {data.reviews_pending
            ? `Faltan ${data.reviews_pending} posts por revisar en el paso 6; las tendencias se calculan cuando termine.`
            : !data.grouping_enabled
              ? "Configura OPENAI_API_KEY para agrupar los subtemas."
              : "Todavía no hay posts sobre el tópico."}
        </p>
      )}
      {!!topics.length && (
        <>
          <TrendSummary topics={topics} />
          <h4 className="pipeline-group">Tópicos por semana</h4>
          <TrendMatrix data={data} topics={topics} selected={selected} onSelect={setSelected} />
          <h4 className="pipeline-group">Mapa de tendencias</h4>
          <TrendQuadrant topics={topics} selected={selected} onSelect={setSelected} />
          {current && <TopicDetail topic={current} />}
        </>
      )}
    </>
  );
}

function TrendSummary({ topics }: { topics: InstagramTrendTopic[] }) {
  const actionable = topics.filter((t) => ACTIONABLE.has(t.state));
  const avoid = topics.filter((t) => t.state === "saturado" || t.state === "enfriandose");
  return (
    <div className="trend-summary">
      <div>
        <small>Para aprovechar</small>
        {actionable.length ? (
          actionable.map((t) => (
            <p key={t.name}>
              <strong>{t.name}</strong> · {trendStates[t.state]} · {ratio(t.traction)} · {t.recent_creators} creadores recientes
            </p>
          ))
        ) : (
          <p className="muted">Ningún tópico cumple hoy los criterios de en caliente, emergente o en ascenso.</p>
        )}
      </div>
      <div>
        <small>Con cuidado</small>
        {avoid.length ? (
          avoid.map((t) => (
            <p key={t.name}>
              <strong>{t.name}</strong> · {trendStates[t.state]} · {ratio(t.traction)}
            </p>
          ))
        ) : (
          <p className="muted">Ninguno saturado ni enfriándose.</p>
        )}
      </div>
    </div>
  );
}

function TrendMatrix({ data, topics, selected, onSelect }: { data: RunTrends; topics: InstagramTrendTopic[]; selected: string; onSelect: (n: string) => void }) {
  return (
    <div className="pipeline-table-wrap">
      <table className="trend-matrix">
        <thead>
          <tr>
            <th>Tópico</th>
            <th>Estado</th>
            {data.weeks.map((w) => <th key={w}>{weekLabel(w)}</th>)}
            <th>Tracción</th>
            <th>Amplitud</th>
            <th>Momentum</th>
          </tr>
        </thead>
        <tbody>
          {topics.map((t) => (
            <tr key={t.name} className={selected === t.name ? "selected" : ""}>
              <td>
                <button className="link-button" onClick={() => onSelect(selected === t.name ? "" : t.name)}>{t.name}</button>
              </td>
              <td><span className={`trend-state ${t.state}`} title={stateNotes[t.state]}>{trendStates[t.state]}</span></td>
              {t.cells.map((c) => {
                const style = cellColor(c.median_performance);
                return (
                  <td key={c.week} className="ig-trend-cell-wrap">
                    {style ? (
                      <span
                        className="ig-trend-cell"
                        style={style}
                        tabIndex={0}
                        title={`${t.name} · semana del ${weekLabel(c.week)}\n${c.posts} posts de ${c.creators} creadores\nRendimiento mediano ${ratio(c.median_performance)}`}
                      >
                        {c.posts}
                      </span>
                    ) : (
                      <span className="ig-trend-cell ig-trend-cell-blank" aria-label="sin posts" />
                    )}
                  </td>
                );
              })}
              <td>{ratio(t.traction)}</td>
              <td>{t.recent_creators} <small className="muted">de {t.creators}</small></td>
              <td title={`Adopción ${signed(t.adoption_change)} · rendimiento ${signed(t.performance_change)}`}>{signed(t.momentum)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="trend-legend">
        <span>Número = posts de la semana. Color = rendimiento mediano frente a lo normal de cada creador:</span>
        <span className="trend-legend-scale">
          <i style={cellColor(0.25)!} /> ×0,25 <i style={cellColor(0.5)!} /> ×0,5 <i style={cellColor(1)!} /> ×1
          <i style={cellColor(2)!} /> ×2 <i style={cellColor(4)!} /> ×4+
        </span>
      </div>
    </div>
  );
}

function TrendQuadrant({ topics, selected, onSelect }: { topics: InstagramTrendTopic[]; selected: string; onSelect: (n: string) => void }) {
  const W = 760, H = 380, PAD = { l: 52, r: 16, t: 16, b: 44 };
  const points = topics.filter((t) => t.traction !== null);
  const xs = points.map((t) => t.momentum ?? 0);
  const ys = points.map((t) => Math.log2(t.traction!));
  const xMax = Math.max(1, ...xs.map(Math.abs)) * 1.1;
  const yMax = Math.max(1, ...ys.map(Math.abs)) * 1.1;
  const x = (v: number) => PAD.l + ((v + xMax) / (2 * xMax)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + ((yMax - v) / (2 * yMax)) * (H - PAD.t - PAD.b);
  const r = (n: number) => 5 + Math.sqrt(n) * 3;
  // Etiquetas selectivas: lo accionable, lo seleccionado, el de mayor tracción y lo saturado o enfriándose.
  // Se colocan en ese orden y se omite la que chocaría con una ya puesta (queda en el tooltip).
  const top = points.reduce<InstagramTrendTopic | null>((best, t) => (!best || (t.traction ?? 0) > (best.traction ?? 0) ? t : best), null);
  const wanted = points
    .filter((t) => ACTIONABLE.has(t.state) || t.name === selected || t === top || t.state === "saturado" || t.state === "enfriandose")
    .sort((a, b) => Number(b.name === selected) - Number(a.name === selected) || Number(ACTIONABLE.has(b.state)) - Number(ACTIONABLE.has(a.state)));
  const placed: { x: number; y: number; w: number; name: string; anchor: "start" | "end" }[] = [];
  for (const t of wanted) {
    const cx = x(t.momentum ?? 0), cy = y(Math.log2(t.traction!)), w = t.name.length * 6.2, gap = r(t.recent_creators) + 4;
    const anchor = cx + gap + w > W - PAD.r ? "end" : "start";
    const lx = anchor === "start" ? cx + gap : cx - gap;
    const box = { x: anchor === "start" ? lx : lx - w, y: cy - 8, w };
    if (placed.some((p) => box.x < p.x + p.w && p.x < box.x + box.w && Math.abs(box.y - p.y) < 14)) continue;
    placed.push({ ...box, name: t.name, anchor });
  }
  const labels = new Map(placed.map((p) => [p.name, p]));
  const xTicks: number[] = [];
  for (let v = -Math.floor(xMax * 2) / 2; v <= xMax; v += 0.5) xTicks.push(v);
  return (
    <div className="trend-quadrant">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Tracción frente a momentum por tópico">
        <line x1={x(0)} x2={x(0)} y1={PAD.t} y2={H - PAD.b} className="axis" />
        <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} className="axis" />
        <text x={W - PAD.r - 4} y={PAD.t + 12} textAnchor="end" className="quadrant-name">Rinde y acelera</text>
        <text x={PAD.l + 4} y={PAD.t + 12} className="quadrant-name">Rinde pero se frena</text>
        <text x={W - PAD.r - 4} y={H - PAD.b - 6} textAnchor="end" className="quadrant-name">Crece sin rendir</text>
        <text x={PAD.l + 4} y={H - PAD.b - 6} className="quadrant-name">Se apaga</text>
        <text x={(PAD.l + W - PAD.r) / 2} y={H - 8} textAnchor="middle" className="axis-label">Momentum (quincena reciente vs anterior) →</text>
        <text x={14} y={(PAD.t + H - PAD.b) / 2} textAnchor="middle" className="axis-label" transform={`rotate(-90 14 ${(PAD.t + H - PAD.b) / 2})`}>
          Tracción (×1 = normal) →
        </text>
        {[0.25, 0.5, 1, 2, 4, 8].filter((v) => Math.abs(Math.log2(v)) <= yMax).map((v) => (
          <text key={v} x={PAD.l - 6} y={y(Math.log2(v)) + 3} textAnchor="end" className="tick">×{v}</text>
        ))}
        {xTicks.map((v) => (
          <text key={v} x={x(v)} y={H - PAD.b + 14} textAnchor="middle" className="tick">{v > 0 ? `+${v}` : v === 0 ? "0" : v}</text>
        ))}
        {points.map((t) => {
          const cx = x(t.momentum ?? 0), cy = y(Math.log2(t.traction!));
          const strong = ACTIONABLE.has(t.state) || t.name === selected;
          return (
            <g key={t.name} className="quadrant-point" onClick={() => onSelect(selected === t.name ? "" : t.name)} tabIndex={0}>
              <title>{`${t.name} · ${trendStates[t.state]}\nTracción ${ratio(t.traction)} · momentum ${signed(t.momentum)}\n${t.recent_creators} creadores recientes · ${t.posts} posts`}</title>
              <circle cx={cx} cy={cy} r={Math.max(12, r(t.recent_creators))} fill="transparent" />
              <circle cx={cx} cy={cy} r={r(t.recent_creators)} fill={strong ? ACCENT : MUTED} stroke="#fcfcfb" strokeWidth={2} />
              {labels.has(t.name) && (
                <text
                  x={labels.get(t.name)!.anchor === "start" ? cx + r(t.recent_creators) + 4 : cx - r(t.recent_creators) - 4}
                  y={cy + 4}
                  textAnchor={labels.get(t.name)!.anchor}
                  className="point-label"
                >
                  {t.name}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <small className="muted">
        Tamaño = creadores en los últimos 14 días. En azul, los tópicos para aprovechar; pasa el cursor o haz clic en uno para ver su detalle.
      </small>
    </div>
  );
}

function TopicDetail({ topic }: { topic: InstagramTrendTopic }) {
  return (
    <section className="trend-detail">
      <h4>{topic.name} <span className={`trend-state ${topic.state}`}>{trendStates[topic.state]}</span></h4>
      <p className="muted">{topic.description} {stateNotes[topic.state]}</p>
      <p>
        {topic.posts} posts de {topic.creators} creadores · {topic.recent_posts} en los últimos 14 días y {topic.previous_posts} en los 14 anteriores ·
        {" "}{topic.formats.reel} reels, {topic.formats.carousel} carruseles, {topic.formats.image} imágenes
      </p>
      {topic.production && (
        <p>
          <strong>Cómo están hechos sus posts más fuertes</strong> ({topic.production.analyzed} analizados):{" "}
          {[topic.production.formato, topic.production.encuadre, topic.production.musica, topic.production.texto_en_pantalla, `gancho: ${topic.production.gancho_tipo}`]
            .map((v) => traitValue(String(v))).join(" · ")}
        </p>
      )}
      <p className="muted">Subtemas: {topic.subtopics.join(", ")}</p>
      <ul className="ig-trend-evidence">
        {topic.evidence.map((e) => (
          <li key={e.shortcode}>
            <a href={e.url} target="_blank" rel="noopener noreferrer">@{e.username} <ArrowUpRight size={11} /></a> {ratio(e.performance)} · {e.caption.slice(0, 120)}
          </li>
        ))}
      </ul>
    </section>
  );
}

const traitNames: Record<string, string> = {
  formato: "Formato", encuadre: "Encuadre", voz_cercana: "Voz cerca del micrófono", microfono_visible: "Micrófono visible",
  musica: "Música", texto_en_pantalla: "Texto en pantalla", gancho_tipo: "Gancho", ritmo_edicion: "Ritmo de edición",
  tono: "Tono", ambiente: "Ambiente", llamada_a_la_accion: "Llamada a la acción",
};
function traitValue(value: string | boolean) {
  if (value === true) return "sí";
  if (value === false) return "no";
  return value.replace(/_/g, " ");
}
const pct = (v: number) => `${Math.round(v * 100)}%`;

export function PatternsStep({ data }: { data: RunPatterns | null }) {
  if (!data) return <p className="muted"><LoaderCircle size={12} className="spin" /> Cargando patrones…</p>;
  const { progress } = data;
  return (
    <>
      <h3>8 · Patrones de contenido</h3>
      <p className="muted">
        Cómo están producidos los reels que funcionan, no de qué hablan. Gemini analiza los primeros {data.clip_seconds} s de los
        reels con mejor rendimiento sobre el tópico. Con reels de control (normales de los mismos creadores) un rasgo es patrón
        solo si aparece bastante más en los destacados.
      </p>
      <p className="muted">
        {progress.pending > 0 && data.enabled && !data.reviews_pending && <LoaderCircle size={12} className="spin" />}{" "}
        {progress.done} de {progress.targets} reels analizados ({data.groups.top} destacados, {data.groups.control} de control)
        {progress.pending > 0 && ` · ${progress.pending} pendientes`}
        {progress.failed > 0 && ` · ${progress.failed} sin análisis (fallaron y quedan vacíos)`}
        {!data.enabled && " · configura GEMINI_API_KEY"}
        {!!data.reviews_pending && ` · esperando a que se revisen ${data.reviews_pending} posts en el paso 6`}
        {progress.pending > 0 && progress.expires_at && ` · los enlaces vencen el ${new Date(progress.expires_at).toLocaleString("es")}`}
      </p>
      {data.groups.top > 0 && data.groups.control === 0 && (
        <>
          <TraitTable title={`Rasgos en común entre los ${data.groups.top} mejores reels`} traits={data.shared} empty="No comparten rasgos dominantes." control={false} />
          <p className="muted">
            Sin grupo de control: estos rasgos inspiran, pero no prueban que expliquen el éxito; los reels normales podrían
            compartirlos. Para contrastar, configura CONTENT_CONTROL_REELS.
          </p>
        </>
      )}
      {data.groups.top > 0 && data.groups.control > 0 && (
        <>
          <TraitTable title="Más frecuente en los destacados" traits={data.patterns} empty="Ningún rasgo separa claramente a los destacados." />
          <TraitTable title="Común a ambos grupos (no explica la diferencia)" traits={data.common} empty="—" />
          <TraitTable title="Más frecuente en el control" traits={data.avoid} empty="—" />
          <p className="muted">
            Muestra chica ({data.groups.top} frente a {data.groups.control}): son indicios para probar, no reglas.
          </p>
        </>
      )}
      <h4 className="pipeline-group">Reels analizados</h4>
      <div className="pipeline-verdicts">
        {data.items.filter((i) => i.features).map((i) => (
          <article key={i.shortcode} className="pipeline-verdict">
            <a href={i.url} target="_blank" rel="noopener noreferrer">
              @{i.username} · {i.group === "top" ? "destacado" : "control"} {ratio(i.performance)} <ArrowUpRight size={11} />
            </a>
            <p><strong>Gancho:</strong> {String(i.features!.gancho)}</p>
            <p className="muted">{String(i.features!.descripcion)}</p>
            <div className="related-account-pills">
              {["formato", "encuadre", "musica", "texto_en_pantalla", "ritmo_edicion"].map((k) => (
                <span key={k} className="pill">{traitValue(i.features![k] as string)}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function TraitTable({ title, traits, empty, control = true }: { title: string; traits: PatternTrait[]; empty: string; control?: boolean }) {
  return (
    <>
      <h4 className="pipeline-group">{title}</h4>
      {traits.length ? (
        <table className="pipeline-table trait-table">
          <thead>
            <tr><th>Rasgo</th><th>Destacados</th>{control && <><th>Control</th><th>Diferencia</th></>}</tr>
          </thead>
          <tbody>
            {traits.map((t) => (
              <tr key={`${t.trait}-${String(t.value)}`}>
                <td>{traitNames[t.trait] || t.trait}: <strong>{traitValue(t.value)}</strong></td>
                <td><span className="trait-bar"><i style={{ width: pct(t.top), background: ACCENT }} /></span> {pct(t.top)}</td>
                {control && (
                  <>
                    <td><span className="trait-bar"><i style={{ width: pct(t.control), background: MUTED }} /></span> {pct(t.control)}</td>
                    <td>{t.lift > 0 ? "+" : ""}{Math.round(t.lift * 100)} pts</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </>
  );
}
