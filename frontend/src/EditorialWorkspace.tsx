import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Copy,
  Download,
  FileText,
  Focus,
  Layers,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import { api } from "./types";
import type { Brand } from "./types";
import type {
  EditorialEvidence,
  EditorialReport,
  EditorialSource,
  EditorialTopic,
} from "./editorialTypes";
import MediaPreview from "./MediaPreview";

const NETWORK: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  linkedin: "LinkedIn",
  youtube: "YouTube",
};
const num = (v: number | null | undefined) =>
  v == null
    ? "N/D"
    : new Intl.NumberFormat("es", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);
const date = (v: string) =>
  new Date(v).toLocaleDateString("es", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
function param(key: string) {
  return new URLSearchParams(location.search).get(key) || "";
}
function saveParams(values: Record<string, string>) {
  const u = new URL(location.href);
  for (const [k, v] of Object.entries(values)) {
    if (v) u.searchParams.set(k, v);
    else u.searchParams.delete(k);
  }
  history.replaceState(null, "", u);
}
function download(name: string, text: string, type: string) {
  const u = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  URL.revokeObjectURL(u);
}
function brief(topic: EditorialTopic, report: EditorialReport) {
  const p = topic.proposals[0];
  return `# ${topic.label}\n\nMarca: ${report.brand_name}\nFuente: ${report.source.id}\nCorte: ${report.observed_at}\n${report.source.demo ? "DEMO SINTÉTICA\n" : ""}\n## Por qué considerarlo\n${topic.why.join("\n\n")}\n\n## Encaje\n${topic.fit}\n\n## Propuesta editorial por validar\n${p.title}\n\n${p.hook}\n\n${p.outline.map((s, i) => `${i + 1}. ${s}`).join("\n")}\n\nMedición: ${p.measurement}\n\n## Evidencia\n${topic.evidence.map((e) => `${e.title}: ${e.url || "Demo sintética"}`).join("\n")}\n\n## Límites\n${report.warnings.join("\n")}\n${report.methodology}\n`;
}

export default function EditorialWorkspace({
  brand,
  requestedSource,
  onDiscover,
  onClassic,
}: {
  brand: Brand;
  requestedSource?: string;
  onDiscover: () => void;
  onClassic: () => void;
}) {
  const [sources, setSources] = useState<EditorialSource[]>([]);
  const [sourceId, setSourceId] = useState(
    param("radar_source") || requestedSource || "",
  );
  const [report, setReport] = useState<EditorialReport | null>(null);
  const [selectedId, setSelectedId] = useState(param("radar_topic"));
  const [search, setSearch] = useState(param("radar_search"));
  const [network, setNetwork] = useState(param("radar_network"));
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  const [copied, setCopied] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    let active = true;
    setError("");
    setLoading(true);
    api<EditorialSource[]>(`/brands/${brand.id}/editorial-sources`)
      .then((data) => {
        if (!active) return;
        setSources(data);
        setSourceId((current) =>
          data.some((s) => s.id === current) ? current : data[0]?.id || "",
        );
        if (!data.length) {
          setReport(null);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [brand.id, revision]);
  useEffect(() => {
    if (!sourceId || !sources.some((s) => s.id === sourceId)) return;
    let active = true;
    setLoading(true);
    setError("");
    setReport(null);
    api<EditorialReport>(
      `/brands/${brand.id}/editorial-report?source=${encodeURIComponent(sourceId)}`,
    )
      .then((data) => {
        if (active) {
          setReport(data);
          setLoading(false);
          setSelectedId((current) =>
            data.topics.some((t) => t.id === current)
              ? current
              : data.topics[0]?.id || "",
          );
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [brand.id, sourceId, sources]);
  useEffect(() => {
    saveParams({
      brand: brand.id,
      radar_source: sourceId,
      radar_topic: selectedId,
      radar_search: search,
      radar_network: network,
    });
  }, [brand.id, sourceId, selectedId, search, network]);
  const topics = useMemo(
    () =>
      report?.topics.filter(
        (t) =>
          (!network || t.networks.includes(network)) &&
          `${t.label} ${t.description}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ) || [],
    [report, network, search],
  );
  const original = topics.find((t) => t.id === selectedId) || topics[0];
  const selected =
    original && network
      ? {
          ...original,
          evidence: original.evidence.filter((e) => e.platform === network),
          series: original.series.filter((s) => s.platform === network),
          proposals: original.proposals.filter(
            (p) => !p.platform || p.platform === network,
          ),
        }
      : original;
  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
    setCopied(false);
  }, [selected?.id, selectedId]);
  const ranking = topics
    .slice(0, 8)
    .map((t) => ({ name: t.label, score: t.priority, id: t.id }));
  const chosen = sources.find((s) => s.id === sourceId);
  const networks = report
    ? Array.from(new Set(report.topics.flatMap((t) => t.networks)))
    : [];
  async function copyBrief() {
    if (!selected || !report) return;
    try {
      await navigator.clipboard.writeText(brief(selected, report));
      setCopied(true);
    } catch {
      setError("No se pudo copiar. Puedes descargar el brief como archivo.");
    }
  }
  return (
    <div className="editorial-workspace">
      <div className="ed-sourcebar">
        <label>
          <Layers size={16} />
          <span>
            Fuente del informe
            <select
              aria-label="Fuente del informe editorial"
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                setSelectedId("");
                setSearch("");
                setNetwork("");
                setCopied(false);
              }}
            >
              {!sources.length && (
                <option value="">Sin corridas guardadas</option>
              )}
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.demo ? "DEMO · " : ""}
                  {s.networks.map((n) => NETWORK[n]).join(" + ")} · {s.label} ·{" "}
                  {date(s.created_at)}
                </option>
              ))}
            </select>
          </span>
        </label>
        <button
          className="button small"
          disabled={loading}
          onClick={() => setRevision((v) => v + 1)}
          aria-label="Actualizar informe guardado"
        >
          <RefreshCw size={15} className={loading ? "spin" : ""} /> Actualizar
        </button>
        <button className="ed-text-button" onClick={onClassic}>
          Ver lotes <ArrowUpRight size={14} />
        </button>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
          <button onClick={() => setRevision((v) => v + 1)}>Reintentar</button>
        </div>
      )}
      {loading && (
        <div className="ed-loading" role="status">
          <LoaderCircle className="spin" size={25} />
          <strong>Conectando señales con tu marca…</strong>
          <span>Consultando resultados guardados.</span>
          <div className="ed-skeleton" />
        </div>
      )}
      {!loading && !report && !error && (
        <div className="ed-empty">
          <Focus size={38} />
          <h2>Tu próximo brief empieza con una búsqueda.</h2>
          <p>
            El paso 3 reúne las corridas de Instagram, TikTok, LinkedIn y
            YouTube. Completa el descubrimiento para ver prioridades y
            propuestas aquí.
          </p>
          <button className="button dark" onClick={onDiscover}>
            Ir al paso 2 <ArrowRight size={16} />
          </button>
        </div>
      )}
      {report && (
        <>
          {report.source.demo && (
            <div className="demo-banner">
              <ShieldCheck size={17} />
              <strong>Demo sintética</strong>
              <span>Cifras y piezas ficticias para explorar el informe.</span>
            </div>
          )}
          <motion.section
            className="ed-hero"
            initial={reduced ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="ed-hero-copy">
              <div className="eyebrow">
                <span className="status-dot" /> PASO 03 · INTELIGENCIA EDITORIAL
              </div>
              <h2>
                La siguiente idea,
                <br />
                <em>con una razón detrás.</em>
              </h2>
              <p>
                {report.topics.length ? (
                  <>
                    Tu muestra abre{" "}
                    <strong>{report.topics.length} líneas de contenido</strong>.
                    Explora la señal, entiende su contexto y conviértela en una
                    prueba para {report.brand_name}.
                  </>
                ) : (
                  "La corrida todavía no tiene temas con evidencia suficiente. Puedes explorar otra fuente o continuar el análisis en el paso 2."
                )}
              </p>
              <div className="ed-hero-meta">
                <span>
                  <ShieldCheck size={14} /> Evidencia trazable
                </span>
                <span>Corte: {date(report.observed_at)}</span>
                <span>
                  {chosen?.networks.map((n) => NETWORK[n]).join(" + ")}
                </span>
              </div>
            </div>
            <div className="ed-hero-index">
              <span>LECTURA DE LA MUESTRA</span>
              <div>
                <strong>{num(report.counts.posts)}</strong>
                <small>piezas analizadas</small>
              </div>
              <div className="ed-hero-index-bottom">
                <span>
                  <b>{num(report.counts.creators)}</b> cuentas
                </span>
                <span>
                  <b>{num(report.counts.topics)}</b> temas
                </span>
              </div>
              <div className="ed-index-line" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
          </motion.section>
          {report.identity_changed && (
            <div className="alert">
              La identidad cambió desde esta corrida. El informe conserva el
              contexto original; ejecuta una nueva búsqueda para usar la
              identidad actual.
            </div>
          )}
          <div className="ed-lens">
            <span>
              <Users size={16} /> TU LENTE
            </span>
            <p>
              {report.identity.audience} <span>· {report.identity.region}</span>
            </p>
            <span className="ed-lens-status">
              {report.identity.method === "step_2_snapshot"
                ? "Contexto guardado de la corrida"
                : `Identidad ${report.identity.status === "confirmed" ? "confirmada" : "por confirmar"}`}
            </span>
          </div>
          <div className="ed-section-heading">
            <div>
              <div className="eyebrow">01 / ENCONTRAR LA OPORTUNIDAD</div>
              <h2>Qué merece tu atención.</h2>
            </div>
            <p>Prioridad editorial dentro de esta corrida, sobre 100.</p>
          </div>
          <div className="ed-controls">
            <label className="ed-search">
              <Search size={17} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar un tema…"
                aria-label="Buscar tema en el informe"
              />
            </label>
            <label className="ed-network">
              Red
              <select
                aria-label="Filtrar informe por red"
                value={network}
                onChange={(e) => setNetwork(e.target.value)}
              >
                <option value="">Todas en esta corrida</option>
                {networks.map((n) => (
                  <option value={n} key={n}>
                    {NETWORK[n]}
                  </option>
                ))}
              </select>
            </label>
            <span aria-live="polite">{topics.length} temas</span>
          </div>
          {!!topics.length && (
            <div className="ed-overview">
              <section className="ed-card ed-ranking">
                <div className="ed-card-heading">
                  <h3>
                    <TrendingUp size={17} /> Mapa de prioridades
                  </h3>
                  <span>0–100</span>
                </div>
                <div
                  className="ed-ranking-chart"
                  role="img"
                  aria-label="Prioridad editorial de los ocho primeros temas. Valores disponibles en la lista de temas."
                >
                  <ResponsiveContainer
                    width="100%"
                    height={Math.max(180, ranking.length * 38)}
                  >
                    <BarChart
                      data={ranking}
                      layout="vertical"
                      margin={{ left: 0, right: 25, top: 5, bottom: 0 }}
                    >
                      <CartesianGrid
                        horizontal={false}
                        stroke="#e7ece6"
                        strokeDasharray="3 4"
                      />
                      <XAxis
                        type="number"
                        domain={[0, 100]}
                        tick={{ fontSize: 10 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        dataKey="name"
                        type="category"
                        width={115}
                        tick={{ fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v: string) =>
                          v.length > 17 ? v.slice(0, 16) + "…" : v
                        }
                      />
                      <Tooltip
                        cursor={{ fill: "#f1f5ed" }}
                        formatter={(v) => [`${v}/100`, "Prioridad"]}
                      />
                      <Bar
                        dataKey="score"
                        radius={[0, 4, 4, 0]}
                        barSize={14}
                        isAnimationActive={!reduced}
                      >
                        {ranking.map((r) => (
                          <Cell
                            key={r.id}
                            fill={r.id === selected?.id ? "#2b563d" : "#a6d48e"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="ed-footnote">
                  Más prioridad sugiere qué explorar primero; no predice alcance
                  ni ventas.
                </p>
              </section>
              <section
                className="ed-topic-list"
                aria-label="Temas ordenados por prioridad"
              >
                {topics.map((t, i) => (
                  <button
                    key={t.id}
                    className={`ed-topic-row ${selected?.id === t.id ? "selected" : ""}`}
                    onClick={() => {
                      setSelectedId(t.id);
                      setCopied(false);
                    }}
                    aria-pressed={selected?.id === t.id}
                  >
                    <span className="ed-topic-number">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="ed-topic-text">
                      <strong>{t.label}</strong>
                      <span>
                        <i className={`ed-stage stage-${t.confidence}`}>
                          {t.stage}
                        </i>
                        <small>Confianza {t.confidence}</small>
                      </span>
                    </span>
                    <span className="ed-topic-score">
                      {t.priority}
                      <small>/100</small>
                    </span>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </section>
            </div>
          )}
          {!topics.length && (
            <div className="ed-empty">
              <Search size={28} />
              <h3>
                {report.topics.length
                  ? "Ningún tema coincide con esos filtros."
                  : "Aún no hay temas listos en esta fuente."}
              </h3>
              <p>
                {report.topics.length
                  ? "Prueba otra búsqueda o red para explorar el informe."
                  : "El paso 2 debe guardar revisiones y métricas suficientes antes de construir las oportunidades."}
              </p>
              {report.topics.length ? (
                <button
                  className="button"
                  onClick={() => {
                    setSearch("");
                    setNetwork("");
                  }}
                >
                  Limpiar filtros
                </button>
              ) : (
                <button className="button" onClick={onDiscover}>
                  Continuar en el paso 2 <ArrowRight size={15} />
                </button>
              )}
            </div>
          )}
          <AnimatePresence mode="wait" initial={false}>
            {selected && (
              <motion.div
                key={selected.id}
                initial={reduced ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: reduced ? 0 : 0.18 }}
              >
                <div className="ed-section-heading ed-topic-heading">
                  <div>
                    <div className="eyebrow">02 / ENTENDER LA SEÑAL</div>
                    <h2>{selected.label}</h2>
                  </div>
                  <span className="ed-stage">{selected.stage}</span>
                </div>
                <div className="ed-insight-grid">
                  <article className="ed-card ed-reason">
                    <span className="ed-card-kicker">
                      <Focus size={16} /> POR QUÉ MIRARLO AHORA
                    </span>
                    {selected.why.length ? (
                      selected.why.map((w, i) => <p key={i}>{w}</p>)
                    ) : (
                      <p>
                        La muestra no incluye una explicación guardada. Examina
                        las piezas antes de formular una hipótesis.
                      </p>
                    )}
                    <div className="ed-signal-grid">
                      {selected.signals.map((s) => (
                        <div key={s.label}>
                          <span>{s.label}</span>
                          <strong>
                            {num(s.value)} <small>{s.unit}</small>
                          </strong>
                        </div>
                      ))}
                    </div>
                  </article>
                  <article className="ed-card ed-fit">
                    <span className="ed-card-kicker">
                      <Users size={16} /> POR QUÉ LE IMPORTA A TU MARCA
                    </span>
                    <p>{selected.fit}</p>
                    <div className="ed-personas">
                      {report.identity.personas.slice(0, 3).map((p) => (
                        <div key={p.role}>
                          <span className="ed-persona-mark">
                            {p.role.charAt(0)}
                          </span>
                          <div>
                            <strong>{p.role}</strong>
                            <small>{p.need}</small>
                          </div>
                        </div>
                      ))}
                    </div>
                  </article>
                </div>
                <div className="ed-chart-grid">
                  {selected.series.map((s) => (
                    <section className="ed-card ed-series" key={s.label}>
                      <div className="ed-card-heading">
                        <div>
                          <h3>{s.label}</h3>
                          <p>{s.unit} · datos guardados del paso 2</p>
                        </div>
                        <span className="ed-network-tag">
                          {NETWORK[s.platform]}
                        </span>
                      </div>
                      {s.points.length > 1 ? (
                        <div className="ed-series-chart">
                          <ResponsiveContainer width="100%" height={220}>
                            <LineChart
                              data={s.points}
                              margin={{
                                left: -15,
                                right: 20,
                                top: 15,
                                bottom: 5,
                              }}
                            >
                              <CartesianGrid
                                vertical={false}
                                stroke="#e8ede6"
                                strokeDasharray="3 4"
                              />
                              <XAxis
                                dataKey="date"
                                tickFormatter={date}
                                tick={{ fontSize: 10 }}
                                axisLine={false}
                                tickLine={false}
                                minTickGap={20}
                              />
                              <YAxis
                                tickFormatter={num}
                                tick={{ fontSize: 10 }}
                                axisLine={false}
                                tickLine={false}
                                domain={[0, "auto"]}
                              />
                              <Tooltip
                                labelFormatter={(v) => date(String(v))}
                                formatter={(v) => [num(Number(v)), s.unit]}
                              />
                              <Line
                                type="linear"
                                dataKey="value"
                                stroke="#426f4e"
                                strokeWidth={2.5}
                                dot={{ r: 3.5, fill: "#fff", strokeWidth: 2 }}
                                activeDot={{ r: 5 }}
                                connectNulls={false}
                                isAnimationActive={!reduced}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      ) : (
                        <p className="ed-chart-empty">
                          Hace falta más de una observación para mostrar
                          evolución.
                        </p>
                      )}
                      <details className="ed-data-table">
                        <summary>Ver valores y fechas</summary>
                        <table>
                          <thead>
                            <tr>
                              <th>Semana / fecha (UTC)</th>
                              <th>{s.unit}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {s.points.map((p) => (
                              <tr key={p.date}>
                                <td>{date(p.date)}</td>
                                <td>{p.value ?? "N/D"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    </section>
                  ))}
                </div>
                <div className="ed-section-heading">
                  <div>
                    <div className="eyebrow">03 / MIRAR LA EVIDENCIA</div>
                    <h2>Las piezas detrás de la señal.</h2>
                  </div>
                  <p>Abre la preview para revisar el contexto original.</p>
                </div>
                <div className="ed-evidence-grid">
                  {selected.evidence.map((e) => (
                    <EvidenceCard
                      item={e}
                      demo={report.source.demo}
                      key={e.id}
                    />
                  ))}
                </div>
                {!selected.evidence.length && (
                  <p className="ed-card">
                    Esta fuente no guardó piezas de referencia para el tema.
                  </p>
                )}
                <div className="ed-section-heading">
                  <div>
                    <div className="eyebrow">04 / CONVERTIR EN CONTENIDO</div>
                    <h2>Un punto de partida para crear.</h2>
                  </div>
                  <div className="ed-actions">
                    <button className="button small" onClick={copyBrief}>
                      {copied ? <Check size={15} /> : <Copy size={15} />}
                      {copied ? "Brief copiado" : "Copiar brief"}
                    </button>
                    <button
                      className="button small"
                      onClick={() =>
                        download(
                          "brief-editorial.md",
                          brief(selected, report),
                          "text/markdown;charset=utf-8",
                        )
                      }
                    >
                      <Download size={15} /> Descargar
                    </button>
                  </div>
                </div>
                <div className="ed-proposals">
                  {selected.proposals.map((p, i) => (
                    <article className="ed-proposal" key={i}>
                      <div className="ed-proposal-head">
                        <span>
                          <Sparkles size={15} /> PROPUESTA EDITORIAL · POR
                          VALIDAR
                        </span>
                        <span>
                          {p.platform
                            ? NETWORK[p.platform]
                            : "Adaptar a la red"}{" "}
                          · {p.format}
                          {p.length ? ` · ${p.length}` : ""}
                        </span>
                      </div>
                      <h3>{p.title}</h3>
                      <blockquote>“{p.hook}”</blockquote>
                      <p className="ed-why-now">{p.why_now}</p>
                      <div className="ed-proposal-body">
                        <div>
                          <span className="ed-card-kicker">
                            ESTRUCTURA SUGERIDA
                          </span>
                          <ol>
                            {p.outline.map((step, j) => (
                              <li key={j}>{step}</li>
                            ))}
                          </ol>
                        </div>
                        <aside>
                          <span className="ed-card-kicker">PARA QUIÉN</span>
                          <strong>{p.persona}</strong>
                          <span className="ed-card-kicker">CÓMO VALIDAR</span>
                          <p>{p.measurement}</p>
                        </aside>
                      </div>
                    </article>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          {!!report.patterns.length && (
            <section className="ed-card ed-patterns">
              <h3>Rasgos de producción para probar</h3>
              <p>
                Frecuencia en piezas destacadas frente al grupo de control. La
                diferencia no demuestra causalidad.
              </p>
              {report.patterns.map((p) => (
                <div className="ed-pattern" key={p.label}>
                  <strong>{p.label}</strong>
                  <span>
                    Destacadas: {Math.round(p.top * 100)}% · n={p.top_n}
                  </span>
                  <meter
                    min={0}
                    max={1}
                    value={p.top}
                    aria-label={`${p.label}, destacadas`}
                  />
                  <span>
                    Control: {Math.round(p.control * 100)}% · n={p.control_n}
                  </span>
                  <meter
                    min={0}
                    max={1}
                    value={p.control}
                    aria-label={`${p.label}, control`}
                  />
                </div>
              ))}
            </section>
          )}
          {!!report.format_insights.length && (
            <section className="ed-card ed-formats">
              <h3>Ganchos y formatos que vale la pena observar</h3>
              <p>
                Asociaciones guardadas por el paso 2; cada rasgo necesita una
                prueba propia con tu audiencia.
              </p>
              <div>
                {report.format_insights.map((p, i) => (
                  <article key={i}>
                    <span className="ed-card-kicker">{p.basis}</span>
                    <strong>{p.label}</strong>
                    <p>
                      {p.support} piezas de apoyo
                      {p.lift != null
                        ? ` · ${p.lift}× de presencia relativa entre las piezas destacadas`
                        : ""}
                      .
                    </p>
                  </article>
                ))}
              </div>
            </section>
          )}
          {!!report.audience_voice.length && (
            <section className="ed-card ed-voices">
              <h3>
                <MessageCircle size={18} /> Lo que pregunta la audiencia
              </h3>
              {report.audience_voice.slice(0, 6).map((v, i) => (
                <p key={i}>
                  {v.theme}
                  <small>{v.mentions} menciones en la muestra</small>
                </p>
              ))}
            </section>
          )}
          <details className="ed-method">
            <summary>
              <ShieldCheck size={17} /> Cobertura, límites y método{" "}
              <span>{report.warnings.length} notas</span>
            </summary>
            <p>{report.methodology}</p>
            <ul>
              {report.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
            <p>
              Este informe consulta resultados guardados. Actualizarlo no inicia
              nuevas extracciones ni análisis con modelos.
            </p>
            <button
              className="button small"
              onClick={() =>
                download(
                  "informe-editorial.json",
                  JSON.stringify(report, null, 2),
                  "application/json",
                )
              }
            >
              <FileText size={15} /> Exportar JSON
            </button>
          </details>
          <div className="ed-bottom">
            <span>
              {report.cost_usd != null
                ? `Costo registrado por el motor de esta corrida: US$${report.cost_usd.toFixed(2)}. `
                : ""}
              De la observación a una prueba con criterio.
            </span>
            <button onClick={onDiscover}>
              Volver al descubrimiento <ArrowRight size={16} />
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function EvidenceCard({
  item: e,
  demo,
}: {
  item: EditorialEvidence;
  demo: boolean;
}) {
  return (
    <article className="ed-card ed-evidence">
      <div className="ed-evidence-head">
        <span className={`ed-platform platform-${e.platform}`}>
          {NETWORK[e.platform]}
        </span>
        <span>
          {e.format === "unknown" ? "Formato sin confirmar" : e.format}
        </span>
      </div>
      <MediaPreview
        key={e.id}
        url={e.url}
        title={e.title}
        descriptor={e.preview}
        demo={demo}
      />
      <div className="ed-evidence-copy">
        <h3>{e.title}</h3>
        {e.author && (
          <span className="ed-author">
            {e.author}
            {e.published_at ? ` · ${date(e.published_at)}` : ""}
          </span>
        )}
        <div className="ed-evidence-metrics">
          <span>
            <b>{num(e.views)}</b> vistas
          </span>
          <span>
            <b>
              {e.performance == null ? "N/D" : `${e.performance.toFixed(2)}×`}
            </b>{" "}
            base del creador
          </span>
        </div>
        <small>
          {e.evidence_level === "search_index"
            ? "Evidencia de índice de búsqueda · sin engagement"
            : demo
              ? "Datos sintéticos"
              : "Observación pública guardada"}
        </small>
        {e.url && (
          <a href={e.url} target="_blank" rel="noreferrer">
            Ver publicación original <ArrowUpRight size={14} />
          </a>
        )}
      </div>
    </article>
  );
}
