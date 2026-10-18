import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowUpRight,
  BadgeCheck,
  Bot,
  Check,
  CircleAlert,
  Globe,
  ListTree,
  LoaderCircle,
  Clapperboard,
  Flame,
  Search,
  TrendingUp,
  Users,
} from "lucide-react";
import { PatternsStep, TrendsStep } from "./TrendsSteps";
import MediaPreview from "./MediaPreview";
import DiscoveryContentResults from "./DiscoveryContentResults";
import { api } from "./types";
import type {
  Brand,
  DiscoveryCandidate,
  DiscoveryPlatform,
  DiscoveryQueryRun,
  DiscoveryRunDetail,
  DiscoveryRunSummary,
  PostLabel,
  QueryPreview,
  RunPatterns,
  RunPosts,
  RunTrends,
} from "./types";

const ACTIVE = new Set(["requesting", "pending"]);
const angles: Record<string, string> = {
  topic: "Tópico",
  context: "Contexto",
  cross: "Cruce",
  region: "Región",
};
const sources: Record<string, string> = {
  url: "URL",
  snippet: "título",
  oembed: "oEmbed",
  video: "video",
};
const types: Record<string, string> = {
  creador: "Creador",
  empresa_afin: "Empresa afín",
  promocion_comercial: "Promoción / comercial",
  gobierno_institucion: "Gobierno / institución",
  medio: "Medio",
  otro: "Otro",
};
const profileStates: Record<string, string> = {
  not_started: "Sin pedir",
  requesting: "Iniciando…",
  pending: "Bright Data trabajando…",
  ready: "Listos",
  failed: "Falló",
  unknown: "Sin confirmar",
};
const postLabels: Record<PostLabel, string> = {
  viral: "Viral",
  sobresaliente: "Sobresaliente",
  normal: "Normal",
  bajo: "Bajo",
  sin_linea_base: "Sin línea base",
};
const formats: Record<string, string> = {
  reel: "Reel",
  video: "Video",
  carousel: "Carrusel",
  image: "Imagen",
  unknown: "—",
};
const kinds: Record<string, string> = {
  educativo: "Educativo",
  noticia: "Noticia",
  promocion_evento: "Promoción / evento",
  venta: "Venta",
  opinion: "Opinión",
  entretenimiento: "Entretenimiento",
  personal: "Personal",
  otro: "Otro",
};
const compact = (n: number | null) =>
  n === null
    ? "—"
    : new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 }).format(n);

// Google a veces ignora site: y devuelve otros dominios; esa query no aporta candidatos.
const siteIgnored = (q: DiscoveryQueryRun) =>
  q.hits.length > 0 && q.hits.every((h) => h.reason === "otro dominio");

function needsPolling(run: DiscoveryRunDetail) {
  if (ACTIVE.has(run.search.state) || ACTIVE.has(run.profiles.state)) return true;
  return (
    run.review_enabled &&
    run.profiles.state === "ready" &&
    run.candidates.some((c) => c.review_status === "pending")
  );
}

type Step = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

/** Búsqueda de creadores por tópico. Instagram parte de Google (SERP); TikTok, de una búsqueda de videos por
 * palabra clave en Bright Data. Desde los candidatos, las etapas son las mismas. */
export default function DiscoveryPanel({ brand, platform = "instagram", onOpenEditorial }: { brand: Brand; platform?: DiscoveryPlatform; onOpenEditorial: (source: string) => void }) {
  const tiktok = platform === "tiktok";
  const [runs, setRuns] = useState<DiscoveryRunSummary[]>([]);
  const [run, setRun] = useState<DiscoveryRunDetail | null>(null);
  const [runId, setRunId] = useState("");
  const [topic, setTopic] = useState("");
  const [maxQueries, setMaxQueries] = useState(3);
  const [preview, setPreview] = useState<QueryPreview | null>(null);
  const [step, setStep] = useState<Step>(1);
  const [posts, setPosts] = useState<RunPosts | null>(null);
  const [trends, setTrends] = useState<RunTrends | null>(null);
  const [patterns, setPatterns] = useState<RunPatterns | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function loadRuns(select?: string) {
    const all = await api<DiscoveryRunSummary[]>(`/brands/${brand.id}/discovery-runs`);
    const list = all.filter((r) => r.platform === platform);
    setRuns(list);
    setRunId((current) => select || current || list[0]?.id || "");
  }

  useEffect(() => {
    setRun(null);
    setRunId("");
    setPreview(null);
    loadRuns().catch((e) => setError(String(e.message || e)));
  }, [brand.id, platform]);

  useEffect(() => {
    setPosts(null);
    setTrends(null);
    setPatterns(null);
    if (!runId) return;
    const controller = new AbortController();
    api<DiscoveryRunDetail>(`/discovery-runs/${runId}`, { signal: controller.signal })
      .then(setRun)
      .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    return () => controller.abort();
  }, [runId]);

  const polling = !!run && needsPolling(run);
  useEffect(() => {
    if (!polling || !run) return;
    const controller = new AbortController();
    // El GET avanza la búsqueda de TikTok o los perfiles y revisa por tandas; nunca inicia una extracción nueva.
    const path = ACTIVE.has(run.search.state) ? `/discovery-runs/${run.id}` : `/discovery-runs/${run.id}/profiles`;
    const timer = setInterval(() => {
      api<DiscoveryRunDetail>(path, { signal: controller.signal })
        .then((data) => {
          setRun(data);
          setRuns((items) =>
            items.map((r) => (r.id === data.id ? { ...r, status: data.status, totals: data.totals, search: data.search, profiles: data.profiles } : r)),
          );
        })
        .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    }, 8000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [polling, run?.id, run?.search.state]);

  // Los posts se cargan al abrir el paso 6; mientras Bright Data trabaja, el GET avanza el trabajo sin iniciar otro.
  const postsActive = !!run && ACTIVE.has(run.posts.state);
  // Con los posts listos, cada consulta transcribe una tanda de reels: se sigue consultando hasta terminar.
  const transcribing =
    !!posts &&
    ((posts.transcripts.enabled && posts.transcripts.pending > 0) ||
      (posts.topic_review.enabled && posts.topic_review.pending > 0));
  useEffect(() => {
    if (!run || step !== 6) return;
    const controller = new AbortController();
    const load = () =>
      api<RunPosts>(`/discovery-runs/${run.id}/posts`, { signal: controller.signal })
        .then((data) => {
          setPosts(data);
          setRun((current) => (current && current.id === data.id ? { ...current, posts: data.posts } : current));
        })
        .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    load();
    const timer = postsActive || transcribing ? setInterval(load, 8000) : undefined;
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [run?.id, step, postsActive, transcribing]);

  // Tendencias: se recalculan al abrir el paso (la unificación con el LLM solo corre si cambiaron los subtemas).
  // Mientras esperan veredictos, se sigue consultando: cada consulta revisa una tanda de posts.
  const trendsWaiting = !!trends && trends.state === "waiting" && trends.reviews_pending > 0;
  useEffect(() => {
    if (!run || step !== 7) return;
    const controller = new AbortController();
    const load = () =>
      api<RunTrends>(`/discovery-runs/${run.id}/trends`, { signal: controller.signal })
        .then(setTrends)
        .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    load();
    const timer = trendsWaiting ? setInterval(load, 8000) : undefined;
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [run?.id, step, trendsWaiting]);

  // Patrones: cada consulta analiza una tanda de reels; se sigue consultando mientras queden pendientes.
  const analyzing = !!patterns && patterns.enabled && !patterns.reviews_pending && patterns.progress.pending > 0;
  useEffect(() => {
    if (!run || step !== 8 || run.platform === "tiktok") return;
    const controller = new AbortController();
    const load = () =>
      api<RunPatterns>(`/discovery-runs/${run.id}/content-patterns`, { signal: controller.signal })
        .then(setPatterns)
        .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    load();
    const timer = analyzing ? setInterval(load, 8000) : undefined;
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [run?.id, step, analyzing]);

  async function act(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  const body = () => JSON.stringify({ topic: topic.trim() || null, max_queries: maxQueries });

  function previewQueries() {
    return act("preview", async () => {
      const request = JSON.stringify({ topic: topic.trim() || null, max_queries: maxQueries, platform });
      setPreview(await api<QueryPreview>(`/brands/${brand.id}/discovery-queries`, { method: "POST", body: request }));
    });
  }

  function runSearch(e: FormEvent) {
    e.preventDefault();
    return act("search", async () => {
      // TikTok responde con la corrida recién creada (búsqueda en curso); Instagram, con la búsqueda ya hecha.
      const id = tiktok
        ? (await api<DiscoveryRunDetail>(`/brands/${brand.id}/tiktok-search`, { method: "POST", body: body() })).id
        : (await api<{ run_id: string }>(`/brands/${brand.id}/creator-search`, { method: "POST", body: body() })).run_id;
      setPreview(null);
      setStep(2);
      await loadRuns(id);
      setRunId(id);
    });
  }

  function fetchProfiles() {
    return act("profiles", async () => {
      const data = await api<DiscoveryRunDetail>(`/discovery-runs/${run!.id}/profiles`, { method: "POST", body: "{}" });
      setRun(data);
      setStep(4);
    });
  }

  function fetchPosts() {
    return act("posts", async () => {
      const data = await api<RunPosts>(`/discovery-runs/${run!.id}/posts`, { method: "POST", body: "{}" });
      setPosts(data);
      setRun((current) => (current ? { ...current, posts: data.posts } : current));
    });
  }

  return (
    <div className="pipeline ds-creator-pipeline">
      <section className="panel ds-query-panel">
        <div className="profile-panel-heading">
          <div>
            <div className="eyebrow">PASO 02 · DESCUBRIMIENTO POR TÓPICO</div>
            <h2>Del tema a las piezas que vale la pena estudiar.</h2>
            <p className="muted">
              {tiktok
                ? "Explora videos de TikTok, identifica creadores afines y compara sus publicaciones con su propio rendimiento habitual."
                : "Encuentra creadores de Instagram, revisa su afinidad y compara las publicaciones de cada cuenta con su propia base."}{" "}
              Cada consulta conserva su evidencia.
            </p>
          </div>
          <Search size={22} />
        </div>
        <form className="pipeline-form" onSubmit={runSearch}>
          <label>
            Tópico
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Vacío: usa los tópicos de la marca"
              maxLength={100}
            />
          </label>
          <label>
            {tiktok ? "Palabras clave" : "Búsquedas"}
            <input
              type="number"
              min={1}
              max={10}
              value={maxQueries}
              onChange={(e) => setMaxQueries(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
            />
          </label>
          <button type="button" className="button" onClick={previewQueries} disabled={!!busy}>
            {busy === "preview" ? <LoaderCircle size={14} className="spin" /> : null} Vista previa (gratis)
          </button>
          <button className="button dark" disabled={!!busy}>
            {busy === "search" ? <LoaderCircle size={14} className="spin" /> : null} Ejecutar búsqueda
          </button>
        </form>
        <small className="muted">
          {tiktok
            ? "Cada palabra clave es una búsqueda de videos en Bright Data (20 por palabra por defecto). Tarda unos minutos; la vista consulta sola el avance."
            : "Cada query es una petición a la SERP de Bright Data. Para Latinoamérica se busca desde Colombia."}
        </small>
        {preview && (
          <ol className="pipeline-preview">
            {preview.queries.map((q) => (
              <li key={q.keywords}>
                <span className="pill">{angles[q.angle] || q.angle}</span> <code>{tiktok ? q.keywords.replace(/"/g, "") : q.query}</code>
              </li>
            ))}
          </ol>
        )}
        {error && <p className="profile-message">{error}</p>}
      </section>

      {!!runs.length && (
        <div className="pipeline-runs">
          {runs.map((r) => (
            <button
              key={r.id}
              className={r.id === runId ? "active" : ""}
              onClick={() => {
                setRunId(r.id);
                setStep(1);
              }}
            >
              <strong>{r.topic || "Tópicos de la marca"}</strong>
              <small>
                {new Date(r.created_at).toLocaleString("es")} ·{" "}
                {ACTIVE.has(r.search.state) ? "buscando videos…" : `${r.totals.candidates} candidatos`}
              </small>
            </button>
          ))}
        </div>
      )}

      {run && (
        <>
          <div className="step-editorial-cta">
            <div><strong>De la búsqueda al brief editorial</strong><p>Explora prioridades, evolución, previews y propuestas con los resultados guardados.</p></div>
            <button className="button dark" onClick={() => onOpenEditorial(`creator:${run.id}`)}>Ver informe editorial <ArrowUpRight size={15} /></button>
          </div>
          <Stepper run={run} step={step} onStep={setStep} />
          <section className="panel pipeline-detail">
            {step === 1 && <QueriesStep run={run} />}
            {step === 2 && (run.platform === "tiktok" ? <VideosStep run={run} /> : <GoogleStep run={run} />)}
            {step === 3 && <CandidatesStep run={run} />}
            {step === 4 && <ProfilesStep run={run} busy={busy === "profiles"} onFetch={fetchProfiles} />}
            {step === 5 && <ReviewStep run={run} />}
            {step === 6 && <PostsStep key={run.id} run={run} data={posts} busy={busy === "posts"} onFetch={fetchPosts} />}
            {step === 7 && <TrendsStep data={trends} />}
            {step === 8 && run.platform !== "tiktok" && <PatternsStep data={patterns} />}
          </section>
        </>
      )}
    </div>
  );
}

function Stepper({ run, step, onStep }: { run: DiscoveryRunDetail; step: Step; onStep: (s: Step) => void }) {
  const ignored = run.queries.filter(siteIgnored).length;
  const errors = run.queries.filter((q) => q.error).length;
  const profilesActive = ACTIVE.has(run.profiles.state);
  const reviewPending = run.candidates.filter((c) => c.review_status === "pending").length;
  const tiktok = run.platform === "tiktok";
  const searching = ACTIVE.has(run.search.state);
  const searchStep = tiktok
    ? {
        n: 2 as Step, icon: Clapperboard, title: "Videos de TikTok",
        value: run.search.state === "ready" ? `${run.totals.results} videos` : profileStates[run.search.state],
        note: run.search.message,
        state: (searching ? "active" : run.search.state === "ready" ? (run.status === "partial" ? "warn" : "done") : "warn") as "active" | "done" | "warn",
      }
    : {
        n: 2 as Step, icon: Globe, title: "Google (SERP)", value: `${run.totals.results} resultados`,
        note: ignored || errors ? `${ignored} queries sin Instagram${errors ? ` · ${errors} con error` : ""}` : `país ${run.countries.join(", ") || "—"}`,
        state: (ignored || errors ? "warn" : "done") as "done" | "warn",
      };
  const items: { n: Step; icon: typeof Search; title: string; value: string; note: string; state: "done" | "active" | "waiting" | "warn" }[] = [
    { n: 1, icon: ListTree, title: tiktok ? "Palabras clave" : "Queries", value: `${run.totals.queries}`, note: run.topic ? `tópico «${run.topic}»` : "tópicos de la marca", state: "done" },
    searchStep,
    {
      n: 3, icon: Users, title: "Candidatos", value: searching ? "—" : `${run.totals.candidates}`,
      note: tiktok ? `${run.totals.discarded} videos descartados` : `${run.totals.discarded} descartados · ${run.totals.unresolved} sin autor`,
      state: searching ? "waiting" : run.totals.candidates ? "done" : "warn",
    },
    {
      n: 4, icon: BadgeCheck, title: "Perfiles", value: profileStates[run.profiles.state],
      note: run.profiles.state === "not_started" ? "pendiente de pedir" : run.profiles.message,
      state: profilesActive ? "active" : run.profiles.state === "ready" ? "done" : run.profiles.state === "not_started" ? "waiting" : "warn",
    },
    {
      n: 5, icon: Bot, title: "Revisión LLM", value: `${run.review_summary.included} pasan`,
      note: !run.review_enabled ? "sin OPENAI_API_KEY" : `${run.review_summary.excluded} descartadas · ${reviewPending} por revisar`,
      state: run.profiles.state !== "ready" ? "waiting" : reviewPending && run.review_enabled ? "active" : "done",
    },
    {
      n: 6, icon: TrendingUp, title: "Posts y relevancia", value: profileStates[run.posts.state],
      note: run.posts.state === "not_started" ? "últimos 30 días · máx. 30 por creador" : run.posts.message,
      state: ACTIVE.has(run.posts.state) ? "active" : run.posts.state === "ready" ? "done" : run.posts.state === "not_started" ? "waiting" : "warn",
    },
    {
      n: 7, icon: Flame, title: "Tendencias", value: "Tópicos",
      note: "en caliente, emergentes, saturados", state: run.posts.state === "ready" ? "done" : "waiting",
    },
    // Patrones con Gemini necesitan el video; el CDN de TikTok no permite descargarlo.
    ...(tiktok
      ? []
      : [{ n: 8 as Step, icon: Clapperboard, title: "Patrones", value: "Contenido", note: "inicio de los 5 mejores reels",
           state: (run.posts.state === "ready" ? "done" : "waiting") as "done" | "waiting" }]),
  ];
  return (
    <ol className="pipeline-steps">
      {items.map(({ n, icon: Icon, title, value, note, state }) => (
        <li key={n}>
          <button className={`${state} ${step === n ? "selected" : ""}`} aria-current={step===n ? "step" : undefined} onClick={() => onStep(n)}>
            <span className="pipeline-step-icon">
              {state === "active" ? <LoaderCircle size={16} className="spin" /> : state === "warn" ? <CircleAlert size={16} /> : state === "done" ? <Check size={16} /> : <Icon size={16} />}
            </span>
            <small>{n} · {title}</small>
            <strong>{value}</strong>
            <span className="pipeline-step-note">{note}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function QueriesStep({ run }: { run: DiscoveryRunDetail }) {
  const tiktok = run.platform === "tiktok";
  return (
    <>
      <h3>1 · {tiktok ? "Palabras clave generadas" : "Queries generadas"}</h3>
      <p className="muted">
        Se arman con reglas a partir del tópico y la identidad de la marca: el tópico solo, con un término
        de contexto que la identidad repite o cruzado con otro tópico de la marca.
        {tiktok && " En TikTok se buscan los mismos términos, sin operadores de Google."}
      </p>
      <table className="pipeline-table">
        <thead>
          <tr><th>#</th><th>Ángulo</th><th>{tiktok ? "Palabra clave" : "Query"}</th><th>País</th><th>{tiktok ? "Videos" : "Resultados"}</th></tr>
        </thead>
        <tbody>
          {run.queries.map((q) => (
            <tr key={q.position}>
              <td>{q.position + 1}</td>
              <td><span className="pill">{angles[q.angle] || q.angle}</span></td>
              <td>
                <code>{q.query}</code>
                {q.fallback_used && <small className="pipeline-flag">plan B: se reintentó sin filtros</small>}
              </td>
              <td>{q.gl || "—"}</td>
              <td>{q.error ? <span className="pipeline-bad">error</span> : q.results}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function GoogleStep({ run }: { run: DiscoveryRunDetail }) {
  return (
    <>
      <h3>2 · Resultados de Google</h3>
      <p className="muted">
        Cada resultado termina como candidato (con el usuario sacado de la URL, del título o de oEmbed),
        descartado (con el motivo) o como post sin autor.
      </p>
      {run.queries.map((q) => (
        <details key={q.position} className="pipeline-query" open={q.position === 0}>
          <summary>
            <code>{q.query}</code>
            <span>
              {q.hits.filter((h) => h.outcome === "candidate").length}/{q.results} útiles
              {siteIgnored(q) && <span className="pipeline-bad"> · Google ignoró site:</span>}
              {q.error && <span className="pipeline-bad"> · {q.error}</span>}
            </span>
          </summary>
          <ul>
            {q.hits.map((h) => (
              <li key={h.rank + h.link} className={h.outcome}>
                <span className="pipeline-rank">#{h.rank}</span>
                {h.outcome === "candidate" ? (
                  <strong>@{h.username} <small>vía {sources[h.author_source || ""] || h.author_source}</small></strong>
                ) : h.outcome === "unresolved" ? (
                  <strong>Sin autor</strong>
                ) : (
                  <strong>Descartado <small>{h.reason}</small></strong>
                )}
                <a href={h.link} target="_blank" rel="noopener noreferrer">
                  {h.link.replace(/^https:\/\/(www\.)?/, "").slice(0, 70)} <ArrowUpRight size={11} />
                </a>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </>
  );
}

function VideosStep({ run }: { run: DiscoveryRunDetail }) {
  return (
    <>
      <h3>2 · Videos encontrados en TikTok</h3>
      <p className="muted">
        Bright Data busca videos por cada palabra clave. Su autor pasa a candidato salvo que sea una cuenta de la marca,
        tenga muy pocos seguidores o solo aparezca con videos antiguos. Si hay más autores que el tope, se priorizan los
        que aparecen en más palabras clave distintas: constancia en el tema, no un viral suelto.
      </p>
      {ACTIVE.has(run.search.state) && (
        <p className="muted"><LoaderCircle size={12} className="spin" /> {profileStates[run.search.state]} · {run.search.message}</p>
      )}
      {!ACTIVE.has(run.search.state) && run.search.state !== "ready" && <p className="profile-message">{run.search.message}</p>}
      {run.queries.map((q) => (
        <details key={q.position} className="pipeline-query" open={q.position === 0}>
          <summary>
            <code>{q.query}</code>
            <span>{q.hits.filter((h) => h.outcome === "candidate").length}/{q.results} de candidatos</span>
          </summary>
          <ul>
            {q.hits.map((h) => (
              <li key={h.rank + h.link} className={h.outcome}>
                <span className="pipeline-rank">#{h.rank}</span>
                {h.outcome === "candidate" ? (
                  <strong>@{h.username}</strong>
                ) : (
                  <strong>{h.username ? `@${h.username} · ` : ""}Descartado <small>{h.reason}</small></strong>
                )}
                <a href={h.link} target="_blank" rel="noopener noreferrer">
                  {h.link.replace(/^https:\/\/(www\.)?/, "").slice(0, 70)} <ArrowUpRight size={11} />
                </a>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </>
  );
}

function CandidatesStep({ run }: { run: DiscoveryRunDetail }) {
  const tiktok = run.platform === "tiktok";
  return (
    <>
      <h3>3 · Candidatos</h3>
      <p className="muted">
        {tiktok
          ? "Autores únicos de los videos, ordenados por cuántas palabras clave distintas los trajeron, cuántos videos suyos aparecieron y su mejor posición."
          : "Cuentas únicas encontradas, ordenadas por cuántas queries las trajeron y su mejor posición."}
      </p>
      <table className="pipeline-table">
        <thead>
          <tr><th>Cuenta</th><th>{tiktok ? "Palabras clave" : "Queries"}</th><th>Mejor posición</th><th>Dónde apareció</th></tr>
        </thead>
        <tbody>
          {run.candidates.map((c) => (
            <tr key={c.username}>
              <td><a href={c.profile_url} target="_blank" rel="noopener noreferrer">@{c.username}</a></td>
              <td>{c.query_hits}</td>
              <td>#{c.best_rank}</td>
              <td>
                {c.sources.map((s, i) => (
                  <a key={s.link + i} href={s.link} target="_blank" rel="noopener noreferrer" className="pipeline-source">
                    #{s.rank} vía {sources[s.author_source] || s.author_source}
                  </a>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Avatar({ c }: { c: DiscoveryCandidate }) {
  const name = c.full_name || c.username;
  return c.avatar_url ? (
    <img src={c.avatar_url} alt="" loading="lazy" />
  ) : (
    <span className="related-account-initial">{name.slice(0, 1).toUpperCase()}</span>
  );
}

function ProfilesStep({ run, busy, onFetch }: { run: DiscoveryRunDetail; busy: boolean; onFetch: () => void }) {
  const state = run.profiles.state;
  const canStart = !ACTIVE.has(state);
  return (
    <>
      <h3>4 · Perfiles (Bright Data)</h3>
      <p className="muted">
        Se paga solo por las cuentas que no estén guardadas o tengan la ficha vencida (30 días); el resto se
        reutiliza sin costo.
      </p>
      <div className="analysis-stamp">
        <span>
          {ACTIVE.has(state) && <LoaderCircle size={12} className="spin" />} {profileStates[state]}
          {run.profiles.message && ` · ${run.profiles.message}`}
        </span>
        {canStart && (
          <button className="button small dark" onClick={onFetch} disabled={busy}>
            {state === "not_started" ? "Traer perfiles" : "Volver a consultar perfiles"}
          </button>
        )}
      </div>
      <div className="pipeline-profiles">
        {run.candidates.map((c) => (
          <article key={c.username} className="related-account">
            <div className="related-account-head">
              <Avatar c={c} />
              <div>
                <strong>{c.full_name || c.username}{c.is_verified && <BadgeCheck size={13} />}</strong>
                <a href={c.profile_url} target="_blank" rel="noopener noreferrer">@{c.username} <ArrowUpRight size={11} /></a>
              </div>
            </div>
            {c.profile_available ? (
              <>
                <div className="related-account-metrics">
                  <span><strong>{compact(c.followers)}</strong> seguidores</span>
                  <span><strong>{compact(c.posts_count)}</strong> {run.platform === "tiktok" ? "videos" : "posts"}</span>
                  {c.likes_total != null && <span><strong>{compact(c.likes_total)}</strong> likes</span>}
                </div>
                {c.biography && <p>{c.biography}</p>}
              </>
            ) : (
              <p className="muted">
                {c.review_status === "awaiting_profile"
                  ? "Descargando perfil…"
                  : c.review_status === "not_requested"
                    ? "Perfil sin pedir."
                    : `Sin ficha (${c.fetch_status || "no disponible"}).`}
              </p>
            )}
          </article>
        ))}
      </div>
    </>
  );
}

function ReviewStep({ run }: { run: DiscoveryRunDetail }) {
  const included = run.candidates.filter((c) => c.included);
  const excluded = run.candidates.filter((c) => c.review && !c.included);
  const pending = run.candidates.filter((c) => !c.review);
  const card = (c: DiscoveryCandidate) => (
    <article key={c.username} className="pipeline-verdict">
      <div className="related-account-head">
        <Avatar c={c} />
        <div>
          <strong>{c.full_name || c.username}</strong>
          <a href={c.profile_url} target="_blank" rel="noopener noreferrer">@{c.username} · {compact(c.followers)} seguidores</a>
        </div>
      </div>
      {c.review && (
        <>
          <div className="related-account-pills">
            <span className="pill">{types[c.review.account_type]}</span>
            <span className="pill">relevancia {c.review.relevance}</span>
            {c.review.is_internal && <span className="pill">interna de la marca</span>}
          </div>
          <p>{c.review.reason}</p>
        </>
      )}
    </article>
  );
  return (
    <>
      <h3>5 · Revisión con LLM</h3>
      <p className="muted">
        gpt-6-luna compara la identidad de la marca con la ficha de cada cuenta. Pasan a tendencias las
        cuentas externas de relevancia alta o media que sean creadores o empresas afines.
      </p>
      {!run.review_enabled && <p className="profile-message">Configura OPENAI_API_KEY para revisar las cuentas.</p>}
      <h4 className="pipeline-group ok">Pasan al análisis de tendencias ({included.length})</h4>
      <div className="pipeline-verdicts">{included.map(card)}</div>
      <h4 className="pipeline-group bad">Descartadas ({excluded.length})</h4>
      <div className="pipeline-verdicts">{excluded.map(card)}</div>
      {!!pending.length && (
        <>
          <h4 className="pipeline-group">Sin revisar todavía ({pending.length})</h4>
          <p className="muted">{pending.map((c) => "@" + c.username).join(", ")}</p>
        </>
      )}
    </>
  );
}

const number = (n: number | null) => (n === null ? "—" : new Intl.NumberFormat("es").format(n));
const percent = (n: number | null) => (n === null ? "—" : `${(n * 100).toFixed(n < 0.01 ? 2 : 1)}%`);
const age = (hours: number) => (hours < 48 ? `${Math.round(hours)} h` : `${Math.round(hours / 24)} d`);

export function PostsStep({ run, data, busy, onFetch }: { run: DiscoveryRunDetail; data: RunPosts | null; busy: boolean; onFetch: () => void }) {
  const [creator, setCreator] = useState("");
  const state = run.posts.state;
  const tiktok = run.platform === "tiktok";
  return (
    <>
      <div className="ds-section-heading"><div><span className="eyebrow">06 · CONTENIDO Y RELEVANCIA</span><h3>Las piezas detrás de la señal.</h3><p>Rendimiento, contexto y referencias de «{data?.topic||run.topic||"los temas de tu marca"}».</p></div><Clapperboard size={26}/></div>
      <details className="ds-method"><summary>Cómo se calcula el rendimiento</summary>
      <p className="muted">
        Trae los {tiktok ? "videos" : "posts"} de los últimos {data?.window_days ?? 30} días (máx. {data?.posts_per_creator ?? 30} por creador) de
        las cuentas que pasan la revisión. Cada {tiktok ? "video" : "post"} se compara con lo que ese mismo creador consigue normalmente:
        {tiktok
          ? " vistas, likes, compartidos y comentarios proyectados según la edad del video, frente a la mediana de sus otros videos. Las vistas pesan más: miden el alcance."
          : " likes y comentarios proyectados según la edad del post, frente a la mediana de sus otros posts del mismo formato. Bright Data no entrega vistas."}
      </p>
      </details>
      <div className="analysis-stamp">
        <span>
          {ACTIVE.has(state) && <LoaderCircle size={12} className="spin" />} {profileStates[state]}
          {run.posts.message && ` · ${run.posts.message}`}
        </span>
        {!ACTIVE.has(state) && (
          <button className="button small dark" onClick={onFetch} disabled={busy || run.profiles.state !== "ready"}>
            {busy && <LoaderCircle size={12} className="spin" />} {state === "not_started" ? "Traer posts" : "Actualizar posts"}
          </button>
        )}
      </div>
      {run.profiles.state !== "ready" && <p className="muted">Primero trae los perfiles (paso 4).</p>}
      {!!data?.items.length && (
        <p className="muted">
          {data.topic_review.pending > 0 && data.topic_review.enabled && <LoaderCircle size={12} className="spin" />}{" "}
          Relevancia para «{data.topic}»: {data.topic_review.on_topic} sobre el tópico · {data.topic_review.off_topic} fuera
          {data.topic_review.pending > 0 && ` · ${data.topic_review.pending} por revisar`}
          {!data.topic_review.enabled && " · configura OPENAI_API_KEY"}
        </p>
      )}
      {!!data?.transcripts.reels && (
        <p className="muted">
          {data.transcripts.pending > 0 && data.transcripts.enabled && <LoaderCircle size={12} className="spin" />}{" "}
          Transcripción (primeros 30 s): {data.transcripts.done} de {data.transcripts.reels} {tiktok ? "videos" : "reels"}
          {data.transcripts.pending > 0 && ` · ${data.transcripts.pending} pendientes`}
          {data.transcripts.failed > 0 && ` · ${data.transcripts.failed} sin video disponible`}
          {!data.transcripts.enabled && " · configura OPENAI_API_KEY"}
          {data.transcripts.pending > 0 && data.transcripts.expires_at &&
            ` · los enlaces vencen el ${new Date(data.transcripts.expires_at).toLocaleString("es")}`}
        </p>
      )}
      {!!data?.excluded_small.length && (
        <p className="muted">
          Fuera por tener menos de {number(data.min_followers)} seguidores:{" "}
          {data.excluded_small.map((c) => `@${c.username} (${compact(c.followers)})`).join(", ")}.
        </p>
      )}
      {!!data?.items.length && <DiscoveryContentResults key={data.id} data={data} creator={creator} onCreator={setCreator} renderTable={items=><PostTable items={items} tiktok={tiktok}/>}/>}
      {!!data?.creators.length && (
        <details className="ds-baselines"><summary>Líneas base de los creadores · {data.creators.length} cuentas</summary><p className="muted">Abre una cuenta para filtrar las piezas de la galería.</p><div className="pipeline-table-wrap">
        <table className="pipeline-table">
          <thead>
            <tr>
              <th>Creador</th><th>Posts</th><th>Por semana</th><th>{tiktok ? "Videos / fotos" : "Reels / estáticos"}</th>
              {tiktok && <th>Vistas típicas</th>}<th>Likes típicos</th><th>Comentarios típicos</th><th>Engagement típico</th>
            </tr>
          </thead>
          <tbody>
            {data.creators.map((c) => (
              <tr key={c.username} className={creator === c.username ? "selected" : ""}>
                <td>
                  <button className="link-button" onClick={() => setCreator(creator === c.username ? "" : c.username)}>
                    @{c.username}
                  </button>{" "}
                  <small className="muted">{compact(c.followers)} seg.</small>
                </td>
                {c.baseline ? (
                  <>
                    <td>{c.baseline.posts}</td>
                    <td>{c.baseline.posts_per_week}</td>
                    <td>{c.baseline.formats.video} / {c.baseline.formats.static}</td>
                    {tiktok && <td>{compact(c.baseline.median_views)}</td>}
                    <td>{compact(c.baseline.median_likes)}</td>
                    <td>{compact(c.baseline.median_comments)}</td>
                    <td>{percent(c.baseline.median_engagement_rate)}</td>
                  </>
                ) : (
                  <td colSpan={tiktok ? 7 : 6} className="muted">{c.posts_fetched_at ? "Sin posts en la ventana" : "Posts sin recoger"}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        </div></details>
      )}
      {!data && state!=="not_started" && <div className="ds-skeleton" role="status">Cargando publicaciones y métricas guardadas…</div>}
      {data && state === "ready" && !data.items.length && <p className="muted">Los creadores no publicaron en la ventana.</p>}
    </>
  );
}

function PostTable({ items, tiktok = false }: { items: RunPosts["items"]; tiktok?: boolean }) {
  return (
          <table className="pipeline-table post-table">
            <thead>
              <tr>
                <th>Post</th><th>Rendimiento</th>{tiktok && <th>Vistas</th>}<th>Likes</th>{tiktok && <th>Compart.</th>}<th>Coment.</th>
                <th>Engagement</th><th>Velocidad</th><th>Edad</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.shortcode}>
                  <td className="post-cell">
                    <a href={p.url} target="_blank" rel="noopener noreferrer">
                      @{p.username} · {formats[p.content_type]} <ArrowUpRight size={11} />
                    </a>
                    {p.topic_review && (
                      <div className="post-topic" title={p.topic_review.reason}>
                        <span className={`pill ${p.topic_review.on_topic ? "" : "muted"}`}>relevancia {p.topic_review.relevance}</span>
                        <span className="pill">{kinds[p.topic_review.content_kind] || p.topic_review.content_kind}</span>
                        {p.topic_review.subtopics.map((t) => <span key={t} className="post-subtopic">{t}</span>)}
                      </div>
                    )}
                    {p.caption && <p>{p.caption.slice(0, 140)}{p.caption.length > 140 ? "…" : ""}</p>}
                    <MediaPreview key={p.url} url={p.url} title={p.caption || p.shortcode} thumbnailUrl={p.thumbnail_url} compact />
                    {p.transcript && (
                      <details className="post-transcript">
                        <summary>Transcripción ({p.transcript_seconds ?? "—"} s)</summary>
                        <p>{p.transcript}</p>
                      </details>
                    )}
                    <small className="muted">
                      {new Date(p.posted_at).toLocaleDateString("es")}
                      {p.is_paid_partnership && " · patrocinado"}
                      {p.is_pinned && " · fijado"}
                      {!!p.coauthors.length && ` · con ${p.coauthors.map((a) => "@" + a).join(", ")}`}
                    </small>
                  </td>
                  <td>
                    <span className={`post-label ${p.label}`}>{postLabels[p.label]}</span>
                    {p.performance !== null && <strong className="post-ratio">×{p.performance}</strong>}
                    <small className="pipeline-detail-note" title={signalTitle(p)}>
                      confianza {p.confidence}
                      {p.provisional && " · provisional"}
                      {p.baseline_scope === "todos" && " · base mixta"}
                    </small>
                    {p.comment_bait && <small className="pipeline-flag">posible «comenta y te envío»</small>}
                  </td>
                  {tiktok && <td>{number(p.views)}{p.signals.views && <small className="muted"> base {compact(p.signals.views.baseline)}</small>}</td>}
                  <td>{number(p.likes)}{p.signals.likes && <small className="muted"> base {compact(p.signals.likes.baseline)}</small>}</td>
                  {tiktok && <td>{number(p.shares)}{p.signals.shares && <small className="muted"> base {compact(p.signals.shares.baseline)}</small>}</td>}
                  <td>{number(p.comments)}{p.signals.comments && <small className="muted"> base {compact(p.signals.comments.baseline)}</small>}</td>
                  <td>{percent(p.engagement_rate)}</td>
                  <td title={p.velocity ? `${p.velocity.observations} lecturas en ${p.velocity.hours} h` : "Hace falta otra lectura con al menos 6 h de diferencia"}>
                    {p.velocity?.likes_per_hour != null ? `+${p.velocity.likes_per_hour} likes/h` : "—"}
                  </td>
                  <td>{age(p.age_hours)}</td>
                </tr>
              ))}
            </tbody>
          </table>
  );
}

const signalNames: Record<string, string> = { views: "Vistas", likes: "Likes", shares: "Compartidos", comments: "Comentarios" };

function signalTitle(p: { signals: RunPosts["items"][number]["signals"]; maturity: number }) {
  const parts = Object.entries(p.signals).map(
    ([name, s]) => `${signalNames[name] || name}: ${s.observed} observadas → ${s.projected} proyectadas vs base ${s.baseline} (×${s.ratio}, z ${s.z}, ${s.baseline_posts} posts)`,
  );
  return [`Madurez estimada ${Math.round(p.maturity * 100)}%`, ...parts].join("\n");
}
