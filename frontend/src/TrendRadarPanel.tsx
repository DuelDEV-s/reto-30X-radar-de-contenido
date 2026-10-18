import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleAlert,
  Lightbulb,
  LoaderCircle,
  MessageCircleQuestion,
  Radar,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { api } from "./types";
import type {
  Brand,
  TrendEngineStatus,
  TrendItem,
  TrendOpportunity,
  TrendPlatform,
  TrendRunDetail,
  TrendRunSummary,
  TrendTopic,
} from "./types";

const ACTIVE = new Set(["queued", "running"]);
const STAGES = [
  { key: "bootstrap", label: "Contexto de marca" },
  { key: "queries", label: "Plan de búsqueda" },
  { key: "youtube", label: "YouTube · demanda" },
  { key: "linkedin", label: "LinkedIn · oferta" },
  { key: "classify", label: "Clasificación" },
  { key: "topics", label: "Tópicos" },
  { key: "scoring", label: "Métricas" },
  { key: "judge", label: "Evaluación" },
  { key: "patterns", label: "Patrones" },
  { key: "opportunities", label: "Propuestas" },
  { key: "report", label: "Informe" },
];
const OPPORTUNITY: Record<TrendOpportunity["type"], string> = {
  linkedin_gap: "Hueco en LinkedIn",
  join_trend: "Sumarse a la tendencia",
  early_bet: "Apuesta temprana",
  language_arbitrage: "Llevarlo al español",
  audience_ask: "Lo pide la audiencia",
};
const STAGE: Record<TrendTopic["stage"], string> = {
  emerging: "Emergente",
  growing: "Creciendo",
  peak: "En pico",
  saturated: "Saturado",
  declining: "En caída",
  insufficient_data: "Sin datos suficientes",
};
const STATUS: Record<TrendTopic["linkedin"]["trend_status"], string> = {
  validated: "Validado por la demanda",
  hype_risk: "Riesgo de moda",
  untested: "Sin validar en YouTube",
  stable: "Estable",
};
const YT_STATUS: Record<TrendTopic["linkedin"]["trend_status"], string> = {
  validated: "Rinde sobre lo normal",
  hype_risk: "Rinde bajo lo normal",
  untested: "Pocos videos",
  stable: "Estable",
};
const DEMAND = { high: "Alta", medium: "Media", low: "Baja" };
const NETWORK: Record<TrendPlatform, string> = { linkedin: "LinkedIn", youtube: "YouTube" };
type Mode = "both" | "linkedin" | "youtube";
const modeOf = (platforms: TrendPlatform[]): Mode => (platforms.length > 1 ? "both" : platforms[0]);
const MODE_COPY: Record<Mode, { title: string; intro: string; scope: string; note?: string }> = {
  both: {
    title: "¿Qué pide tu audiencia y quién lo está publicando?",
    intro:
      "YouTube mide la demanda real (vistas frente a lo normal de cada canal) y LinkedIn muestra cuánto se publica del tema. Donde la demanda supera a la oferta hay una oportunidad, y el radar la convierte en propuestas con evidencia.",
    scope: "Brecha demanda/oferta · propuestas para ambas redes",
  },
  linkedin: {
    title: "¿Qué temas crecen en LinkedIn y quién los publica?",
    intro:
      "Busca posts públicos de LinkedIn sobre tus tópicos, mide qué temas ganan publicaciones semana a semana y cuántos autores los cubren, y propone contenido para LinkedIn.",
    scope: "Solo LinkedIn · sin YouTube",
    note: "LinkedIn no expone vistas ni reacciones, así que sin YouTube no se mide la demanda. Combina LinkedIn + YouTube para ver la brecha entre lo que la audiencia consume y lo que se publica.",
  },
  youtube: {
    title: "¿Qué temas premia hoy la audiencia en YouTube?",
    intro:
      "Busca videos sobre tus tópicos, compara sus vistas con lo normal de cada canal para detectar qué despega, lee las preguntas de la audiencia y propone videos y shorts.",
    scope: "Solo YouTube · sin LinkedIn",
    note: "Sin LinkedIn no se mide cuánto se publica de cada tema. Combina LinkedIn + YouTube para encontrar huecos donde la demanda supera a la oferta.",
  },
};
const compact = (n: number) =>
  new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const pct = (n: number) => `${n > 0 ? "+" : ""}${Math.round(n * 100)}%`;
const usd = (n: number) => `US$${n.toFixed(2)}`;

// Herramientas, marcas o eventos: se omiten las frases largas que repiten el tópico.
const entities = (t: TrendTopic) =>
  t.entities.filter((e) => e.length <= 28 && e.toLowerCase() !== t.label.toLowerCase()).slice(0, 4);

function stageIndex(stage: string) {
  if (stage === "batch" || stage === "done") return STAGES.length;
  return Math.max(0, STAGES.findIndex((s) => stage.startsWith(s.key)));
}

export default function TrendRadarPanel({
  brand,
  platforms,
  onOpenBatch,
}: {
  brand: Brand;
  platforms: TrendPlatform[];
  onOpenBatch: (batchId: string) => void;
}) {
  const [engine, setEngine] = useState<TrendEngineStatus | null>(null);
  const [runs, setRuns] = useState<TrendRunSummary[]>([]);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<TrendRunDetail | null>(null);
  const [windowDays, setWindowDays] = useState(28);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Each selection (LinkedIn, YouTube or both) is its own radar: only its runs are listed.
  const key = [...platforms].sort().join("+");
  const visible = runs.filter((r) => [...r.platforms].sort().join("+") === key);

  async function loadRuns(select?: string) {
    const list = await api<TrendRunSummary[]>(`/brands/${brand.id}/trend-runs`);
    setRuns(list);
    if (select) setRunId(select);
  }

  useEffect(() => {
    setRuns([]);
    setRun(null);
    setRunId("");
    setError("");
    api<TrendEngineStatus>("/trend-engine").then(setEngine).catch(() => setEngine(null));
    loadRuns().catch((e) => setError(e.message));
  }, [brand.id]);

  useEffect(() => {
    if (visible.some((r) => r.id === runId)) return;
    setRun(null);
    setRunId(visible[0]?.id || "");
  }, [key, runs]);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    api<TrendRunDetail>(`/trend-runs/${runId}`, { signal: controller.signal })
      .then(setRun)
      .catch((e) => !controller.signal.aborted && setError(e.message));
    return () => controller.abort();
  }, [runId]);

  const active = !!run && ACTIVE.has(run.status);
  useEffect(() => {
    if (!active || !run) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      api<TrendRunDetail>(`/trend-runs/${run.id}`, { signal: controller.signal })
        .then((data) => {
          setRun(data);
          setError("");
          if (!ACTIVE.has(data.status)) loadRuns(data.id).catch(() => {});
        })
        .catch((e) => !controller.signal.aborted && setError(e.message));
    }, 4000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [active, run?.id]);

  async function start(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<TrendRunSummary>(`/brands/${brand.id}/trend-runs`, {
        method: "POST",
        body: JSON.stringify({ platforms, window_days: windowDays }),
      });
      await loadRuns(created.id);
      setRunId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const label = platforms.map((p) => NETWORK[p]).join(" + ");
  const anyActive = runs.some((r) => ACTIVE.has(r.status));
  const copy = MODE_COPY[modeOf(platforms)];
  return (
    <div className="trend-radar">
      <section className="panel">
        <div className="profile-panel-heading">
          <div>
            <div className="eyebrow">PASO 02 · RADAR {label.toUpperCase()}</div>
            <h2>{copy.title}</h2>
            <p className="muted">{copy.intro} Solo APIs oficiales y contenido público.</p>
          </div>
          <Radar size={22} />
        </div>
        {engine && !engine.configured && (
          <p className="profile-message">
            Falta configurar en el servidor: {engine.missing.join(", ")}. Agrégalas al .env de Compose y reinicia la
            API.
          </p>
        )}
        <form className="trend-form" onSubmit={start}>
          <label>
            Ventana de análisis
            <select value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
              <option value={14}>Últimos 14 días</option>
              <option value={28}>Últimos 28 días</option>
              <option value={56}>Últimas 8 semanas</option>
              <option value={90}>Últimos 90 días</option>
            </select>
          </label>
          <div className="trend-form-scope">
            <small>Muestra</small>
            <strong>{label}</strong>
            <span>{copy.scope}</span>
          </div>
          <button className="button dark" disabled={busy || anyActive || (engine ? !engine.configured : false)}>
            {busy || anyActive ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />}
            {anyActive ? "Radar en curso…" : "Ejecutar radar"}
          </button>
        </form>
        <small className="muted">
          Usa los tópicos y personas de la identidad guardada. Tarda de 3 a 6 minutos; puedes cambiar de pestaña
          mientras corre.
          {engine && ` Modelos: ${engine.models.bulk} en lote y ${engine.models.top} para propuestas.`}
        </small>
        {copy.note && <p className="trend-mode-note">{copy.note}</p>}
        {error && <p className="profile-message">{error}</p>}
      </section>

      {!!visible.length && (
        <div className="pipeline-runs">
          {visible.map((r) => (
            <button key={r.id} className={r.id === runId ? "active" : ""} onClick={() => setRunId(r.id)}>
              <strong>Radar · {r.window_days} días</strong>
              <small>
                {new Date(r.created_at).toLocaleString("es")} ·{" "}
                {r.status === "done"
                  ? `${r.totals?.opportunities ?? 0} propuestas`
                  : r.status === "failed"
                    ? "falló"
                    : "en curso"}
              </small>
            </button>
          ))}
        </div>
      )}

      {!run ? (
        !visible.length && (
          <div className="empty">
            <Radar size={32} />
            <h3>Tu primer radar de {label}</h3>
            <p>Ejecuta el radar para ver qué temas crecen, dónde hay hueco y qué publicar esta semana.</p>
          </div>
        )
      ) : ACTIVE.has(run.status) ? (
        <Progress run={run} />
      ) : run.status === "failed" ? (
        <section className="panel trend-failed">
          <CircleAlert size={20} />
          <div>
            <h3>La corrida no terminó</h3>
            <p>{run.error}</p>
          </div>
        </section>
      ) : run.report ? (
        <Results run={run} onOpenBatch={onOpenBatch} />
      ) : null}
    </div>
  );
}

function Progress({ run }: { run: TrendRunDetail }) {
  const current = stageIndex(run.stage);
  return (
    <section className="panel">
      <div className="analysis-stamp">
        <span>
          <LoaderCircle size={12} className="spin" /> Radar en curso · iniciado{" "}
          {new Date(run.created_at).toLocaleTimeString("es")}
        </span>
      </div>
      <ol className="trend-progress">
        {STAGES.map((s, i) => (
          <li key={s.key} className={i < current ? "done" : i === current ? "active" : ""}>
            <span>{i < current ? <Check size={12} /> : i === current ? <LoaderCircle size={12} className="spin" /> : i + 1}</span>
            {s.label}
          </li>
        ))}
      </ol>
    </section>
  );
}

function Results({ run, onOpenBatch }: { run: TrendRunDetail; onOpenBatch: (batchId: string) => void }) {
  const report = run.report!;
  const items = useMemo(() => new Map(report.items.map((i) => [i.item_id, i])), [report]);
  const topics = useMemo(() => new Map(report.topics.map((t) => [t.topic_id, t])), [report]);
  const personas = useMemo(
    () => new Map(run.identity.personas.map((p) => [p.id, p.name])),
    [run.identity],
  );
  const platforms = run.platforms;
  const mode = modeOf(platforms);
  const useYt = platforms.includes("youtube");
  const useLi = platforms.includes("linkedin");
  const cost = report.run.cost_usd.search + report.run.cost_usd.llm;
  const target = platforms.map((p) => NETWORK[p]).join(" y ");
  return (
    <>
      <div className="stats trend-stats">
        <Stat label="Propuestas" value={String(report.opportunities.length)} note={`Para publicar en ${target}`} />
        <Stat label="Tópicos detectados" value={String(report.topics.length)} note={`${report.run.window.from} → ${report.run.window.to}`} />
        {useLi && (
          <Stat label="Posts de LinkedIn" value={compact(report.run.sources.linkedin.items)} note="Públicos, vía índices de búsqueda" />
        )}
        {useYt && (
          <Stat label="Videos de YouTube" value={compact(report.run.sources.youtube.items)} note={`${report.run.sources.youtube.creators} canales`} />
        )}
        {mode !== "both" && <Stat label="Costo de la corrida" value={usd(cost)} note="Búsquedas y modelos" />}
      </div>

      <section className="panel">
        <div className="trend-section-head">
          <div>
            <h2>Qué publicar esta semana</h2>
            <p className="muted">
              Ordenadas por oportunidad:{" "}
              {mode === "both"
                ? "brecha demanda/oferta"
                : mode === "youtube"
                  ? "demanda y rendimiento de los videos"
                  : "crecimiento de publicaciones con pocos autores"}
              , afinidad con tus personas y lo que tu marca aún no cubre.
            </p>
          </div>
          {run.batch_id && (
            <button className="button small" onClick={() => onOpenBatch(run.batch_id!)}>
              Ver en el radar (paso 3) <ArrowRight size={14} />
            </button>
          )}
        </div>
        {report.opportunities.length ? (
          <div className="trend-opportunities">
            {report.opportunities.map((o) => (
              <OpportunityCard
                key={o.id}
                o={o}
                topic={topics.get(o.topic_id)}
                persona={personas.get(o.persona) || o.persona}
                items={items}
                showNetwork={mode === "both"}
              />
            ))}
          </div>
        ) : (
          <p className="muted">No hubo oportunidades con evidencia suficiente en esta ventana. Prueba una ventana más amplia.</p>
        )}
      </section>

      <section className="panel">
        <h2>Tópicos del mercado</h2>
        <p className="muted">
          {mode === "both"
            ? "Brecha = demanda en YouTube menos oferta en LinkedIn (de −100 a +100). Un valor alto indica que la audiencia lo quiere y pocos lo publican."
            : mode === "youtube"
              ? "Demanda = atención semanal de los videos del tema; ×N = cuánto rinden frente a lo normal de su canal."
              : "Posts y autores por semana en LinkedIn. Un tema que crece con pocos autores es una oportunidad para llegar primero."}
        </p>
        <div className="pipeline-table-wrap">
          <table className="pipeline-table trend-table">
            <thead>
              <tr>
                <th>Tópico</th>
                <th>Etapa</th>
                {useLi && <th>LinkedIn · posts por semana</th>}
                {useYt && <th>Demanda YouTube</th>}
                {mode === "both" && <th>Brecha</th>}
                <th>Prioridad</th>
              </tr>
            </thead>
            <tbody>
              {report.topics.map((t) => (
                <tr key={t.topic_id}>
                  <td>
                    <strong>{t.label}</strong>
                    {entities(t).length > 0 && <small className="trend-entities">{entities(t).join(" · ")}</small>}
                  </td>
                  <td>
                    <span className={`trend-chip stage-${t.stage}`}>{STAGE[t.stage]}</span>
                    {mode !== "linkedin" && (
                      <small className={`trend-status status-${t.linkedin.trend_status}`}>
                        {(mode === "youtube" ? YT_STATUS : STATUS)[t.linkedin.trend_status]}
                      </small>
                    )}
                  </td>
                  {useLi && (
                  <td>
                    <div className="trend-cell">
                      <Bars values={t.linkedin.timeseries.map((w) => w.posts)} />
                      <span>
                        {t.linkedin.posts_7d} en 7 días · {t.linkedin.authors_7d} autores · {pct(t.linkedin.growth_wow)}
                      </span>
                    </div>
                  </td>
                  )}
                  {useYt && (
                  <td>
                    <div className="trend-cell">
                      <Line values={t.demand.timeseries.map((w) => w.attention)} />
                      <span>
                        {DEMAND[t.demand.level]} · {pct(t.demand.momentum_wow)}
                        {t.demand.median_outlier !== null && ` · ${t.demand.median_outlier}x`}
                      </span>
                    </div>
                  </td>
                  )}
                  {mode === "both" && (
                    <td>
                      <Gap value={t.linkedin.li_gap} />
                    </td>
                  )}
                  <td>
                    <strong>{Math.round(t.opportunity_score * 100)}</strong>
                    <small className="trend-entities">confianza {Math.round(t.confidence * 100)}%</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={useYt ? "trend-columns" : "trend-columns single"}>
        <section className="panel">
          <h3>
            <TrendingUp size={16} /> Ganchos que funcionan
          </h3>
          {report.patterns.length ? (
            report.patterns.map((p) => (
              <div className="trend-pattern" key={p.pattern + p.evidence}>
                <div>
                  <strong>{p.label}</strong>
                  <small>
                    {p.evidence === "youtube_lift"
                      ? `${p.lift}x más frecuente en videos que superan 2x lo normal · ${p.support} videos`
                      : `Usado por ${p.support} de las voces más visibles de LinkedIn`}
                  </small>
                </div>
              </div>
            ))
          ) : (
            <p className="muted">Sin muestra suficiente para medir patrones en esta corrida.</p>
          )}
        </section>
        {useYt && (
        <section className="panel">
          <h3>
            <MessageCircleQuestion size={16} /> Lo que pregunta la audiencia
          </h3>
          {report.audience_voice.length ? (
            report.audience_voice.map((a) => (
              <div className="trend-pattern" key={a.theme}>
                <div>
                  <strong>{a.theme}</strong>
                  <small>
                    {a.mentions} menciones · {a.type === "question" ? "pregunta" : a.type === "objection" ? "objeción" : "pedido"}
                    {a.topic_id && topics.get(a.topic_id) ? ` · ${topics.get(a.topic_id)!.label}` : ""}
                  </small>
                </div>
              </div>
            ))
          ) : (
            <p className="muted">Sin comentarios suficientes en los videos destacados.</p>
          )}
        </section>
        )}
      </div>

      <details className="panel trend-method">
        <summary>Cómo se calculó, costo y límites</summary>
        <p>
          Corrida del {new Date(report.run.generated_at).toLocaleString("es")} · costo {usd(cost)}
          {useYt && ` · cuota de YouTube ${report.run.sources.youtube.quota_used} unidades`} · cobertura{" "}
          {report.data_quality.coverage_level}.
        </p>
        {useLi && (
          <p>
            LinkedIn no expone reacciones ni vistas por API: el radar mide cuántos posts y autores publican cada tema y
            su visibilidad en los índices de búsqueda, nunca cifras de engagement.
          </p>
        )}
        {useYt && (
          <p>
            Las vistas vienen de la API oficial de YouTube. La serie de cada video crece con cada observación (una al
            descubrirlo y otra cada pocas horas); los videos con vistas observadas quedan como lote del paso 3.
          </p>
        )}
        {report.data_quality.warnings.map((w) => (
          <p key={w}>• {w}</p>
        ))}
      </details>
    </>
  );
}

function OpportunityCard({
  o,
  topic,
  persona,
  items,
  showNetwork,
}: {
  o: TrendOpportunity;
  topic?: TrendTopic;
  persona: string;
  items: Map<string, TrendItem>;
  showNetwork: boolean;
}) {
  const [first, ...rest] = o.proposal.title_options;
  return (
    <article className="trend-opportunity">
      <div className="trend-opportunity-head">
        <span className={`trend-chip type-${o.type}`}>{OPPORTUNITY[o.type]}</span>
        <span className="trend-score" title="Puntaje de oportunidad">
          <i style={{ width: `${Math.min(100, Math.round(o.score * 100))}%` }} />
          {Math.round(o.score * 100)}
        </span>
      </div>
      {topic && <small className="trend-topic-label">{topic.label}</small>}
      <h3>{first}</h3>
      <p className="trend-why">
        <Lightbulb size={13} /> {o.why_now}
      </p>
      <blockquote>{o.proposal.hook}</blockquote>
      <div className="related-account-pills">
        {showNetwork && <span className={`pill net-pill ${o.platform}`}>{NETWORK[o.platform]}</span>}
        <span className="pill">{persona}</span>
        <span className="pill">{o.format}</span>
        <span className="pill">{o.proposal.length}</span>
      </div>
      <details>
        <summary>Estructura y otros títulos</summary>
        <ol>
          {o.proposal.outline.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {!!rest.length && (
          <ul className="trend-alt-titles">
            {rest.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
      </details>
      <div className="trend-evidence">
        <small>Evidencia</small>
        {o.evidence.map((id) => {
          const item = items.get(id);
          if (!item) return null;
          const youtube = item.platform === "youtube";
          return (
            <a key={id} href={item.url} target="_blank" rel="noopener noreferrer" className={youtube ? "yt" : "li"}>
              <span>{youtube ? "YT" : "in"}</span>
              <em>{(item.title || item.excerpt || item.url).replace(/ on LinkedIn:| en LinkedIn:/, ":").slice(0, 90)}</em>
              {youtube && item.metrics && (
                <b>
                  {compact(item.metrics.views)} vistas{item.metrics.outlier !== null && ` · ${item.metrics.outlier}x`}
                </b>
              )}
              <ArrowUpRight size={11} />
            </a>
          );
        })}
      </div>
    </article>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="stat">
      <div>{label}</div>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function Bars({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return (
    <svg className="trend-spark" viewBox={`0 0 ${values.length * 9} 24`} role="img" aria-label={`Posts por semana: ${values.join(", ")}`}>
      {values.map((v, i) => (
        <rect key={i} x={i * 9 + 1} y={24 - (v / max) * 22 - 1} width="6" height={(v / max) * 22 + 1} rx="1.5" fill="currentColor" />
      ))}
    </svg>
  );
}

function Line({ values }: { values: number[] }) {
  const max = Math.max(...values, 0.0001);
  const w = Math.max(values.length - 1, 1) * 12;
  const points = values.map((v, i) => `${i * 12},${23 - (v / max) * 21}`).join(" ");
  return (
    <svg className="trend-spark line" viewBox={`-2 0 ${w + 4} 24`} role="img" aria-label="Demanda semanal">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

function Gap({ value }: { value: number }) {
  const width = Math.min(50, Math.abs(value) * 50);
  return (
    <div className="trend-gap" title="Brecha demanda/oferta">
      <span>
        <i className={value >= 0 ? "pos" : "neg"} style={value >= 0 ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }} />
      </span>
      <strong className={value >= 0.3 ? "pos" : value < 0 ? "neg" : ""}>{value > 0 ? "+" : ""}{Math.round(value * 100)}</strong>
    </div>
  );
}
