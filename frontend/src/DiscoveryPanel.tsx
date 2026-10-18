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
  Search,
  Users,
} from "lucide-react";
import { api } from "./types";
import type {
  Brand,
  DiscoveryCandidate,
  DiscoveryQueryRun,
  DiscoveryRunDetail,
  DiscoveryRunSummary,
  QueryPreview,
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
const compact = (n: number | null) =>
  n === null
    ? "—"
    : new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 }).format(n);

// Google a veces ignora site: y devuelve otros dominios; esa query no aporta candidatos.
const siteIgnored = (q: DiscoveryQueryRun) =>
  q.hits.length > 0 && q.hits.every((h) => h.reason === "otro dominio");

function needsPolling(run: DiscoveryRunDetail) {
  if (ACTIVE.has(run.profiles.state)) return true;
  return (
    run.review_enabled &&
    run.profiles.state === "ready" &&
    run.candidates.some((c) => c.review_status === "pending")
  );
}

type Step = 1 | 2 | 3 | 4 | 5;

export default function DiscoveryPanel({ brand }: { brand: Brand }) {
  const [runs, setRuns] = useState<DiscoveryRunSummary[]>([]);
  const [run, setRun] = useState<DiscoveryRunDetail | null>(null);
  const [runId, setRunId] = useState("");
  const [topic, setTopic] = useState("");
  const [maxQueries, setMaxQueries] = useState(3);
  const [preview, setPreview] = useState<QueryPreview | null>(null);
  const [step, setStep] = useState<Step>(1);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function loadRuns(select?: string) {
    const list = await api<DiscoveryRunSummary[]>(`/brands/${brand.id}/discovery-runs`);
    setRuns(list);
    setRunId((current) => select || current || list[0]?.id || "");
  }

  useEffect(() => {
    setRun(null);
    setRunId("");
    setPreview(null);
    loadRuns().catch((e) => setError(String(e.message || e)));
  }, [brand.id]);

  useEffect(() => {
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
    // El GET avanza los perfiles y revisa por tandas; nunca inicia una extracción nueva.
    const timer = setInterval(() => {
      api<DiscoveryRunDetail>(`/discovery-runs/${run.id}/profiles`, { signal: controller.signal })
        .then((data) => {
          setRun(data);
          setRuns((items) => items.map((r) => (r.id === data.id ? { ...r, profiles: data.profiles } : r)));
        })
        .catch((e) => !controller.signal.aborted && setError(String(e.message || e)));
    }, 8000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [polling, run?.id]);

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
      setPreview(await api<QueryPreview>(`/brands/${brand.id}/discovery-queries`, { method: "POST", body: body() }));
    });
  }

  function runSearch(e: FormEvent) {
    e.preventDefault();
    return act("search", async () => {
      const result = await api<{ run_id: string }>(`/brands/${brand.id}/creator-search`, { method: "POST", body: body() });
      setPreview(null);
      setStep(2);
      await loadRuns(result.run_id);
      setRunId(result.run_id);
    });
  }

  function fetchProfiles() {
    return act("profiles", async () => {
      const data = await api<DiscoveryRunDetail>(`/discovery-runs/${run!.id}/profiles`, { method: "POST", body: "{}" });
      setRun(data);
      setStep(4);
    });
  }

  return (
    <div className="pipeline">
      <section className="panel">
        <div className="profile-panel-heading">
          <div>
            <div className="eyebrow">PASO 02 · DESCUBRIMIENTO POR TÓPICO</div>
            <h2>¿Quién está hablando de este tema?</h2>
            <p className="muted">
              Busca cuentas de Instagram que publican sobre un tópico, trae su perfil y decide con
              un LLM cuáles pasan al análisis de tendencias. Cada corrida queda guardada.
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
            Queries
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
          Cada query es una petición a la SERP de Bright Data. Para Latinoamérica se busca desde Colombia.
        </small>
        {preview && (
          <ol className="pipeline-preview">
            {preview.queries.map((q) => (
              <li key={q.keywords}>
                <span className="pill">{angles[q.angle] || q.angle}</span> <code>{q.query}</code>
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
                {new Date(r.created_at).toLocaleString("es")} · {r.totals.candidates} candidatos
              </small>
            </button>
          ))}
        </div>
      )}

      {run && (
        <>
          <Stepper run={run} step={step} onStep={setStep} />
          <section className="panel pipeline-detail">
            {step === 1 && <QueriesStep run={run} />}
            {step === 2 && <GoogleStep run={run} />}
            {step === 3 && <CandidatesStep run={run} />}
            {step === 4 && <ProfilesStep run={run} busy={busy === "profiles"} onFetch={fetchProfiles} />}
            {step === 5 && <ReviewStep run={run} />}
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
  const items: { n: Step; icon: typeof Search; title: string; value: string; note: string; state: "done" | "active" | "waiting" | "warn" }[] = [
    { n: 1, icon: ListTree, title: "Queries", value: `${run.totals.queries}`, note: run.topic ? `tópico «${run.topic}»` : "tópicos de la marca", state: "done" },
    {
      n: 2, icon: Globe, title: "Google (SERP)", value: `${run.totals.results} resultados`,
      note: ignored || errors ? `${ignored} queries sin Instagram${errors ? ` · ${errors} con error` : ""}` : `país ${run.countries.join(", ") || "—"}`,
      state: ignored || errors ? "warn" : "done",
    },
    {
      n: 3, icon: Users, title: "Candidatos", value: `${run.totals.candidates}`,
      note: `${run.totals.discarded} descartados · ${run.totals.unresolved} sin autor`, state: run.totals.candidates ? "done" : "warn",
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
  ];
  return (
    <ol className="pipeline-steps">
      {items.map(({ n, icon: Icon, title, value, note, state }) => (
        <li key={n}>
          <button className={`${state} ${step === n ? "selected" : ""}`} onClick={() => onStep(n)}>
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
  return (
    <>
      <h3>1 · Queries generadas</h3>
      <p className="muted">
        Se arman con reglas a partir del tópico y la identidad de la marca: el tópico solo, con un término
        de contexto que la identidad repite o cruzado con otro tópico de la marca.
      </p>
      <table className="pipeline-table">
        <thead>
          <tr><th>#</th><th>Ángulo</th><th>Query</th><th>País</th><th>Resultados</th></tr>
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

function CandidatesStep({ run }: { run: DiscoveryRunDetail }) {
  return (
    <>
      <h3>3 · Candidatos</h3>
      <p className="muted">Cuentas únicas encontradas, ordenadas por cuántas queries las trajeron y su mejor posición.</p>
      <table className="pipeline-table">
        <thead>
          <tr><th>Cuenta</th><th>Queries</th><th>Mejor posición</th><th>Dónde apareció</th></tr>
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
                  <span><strong>{compact(c.posts_count)}</strong> posts</span>
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
