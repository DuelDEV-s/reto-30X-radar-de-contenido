import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight,
  Check,
  CircleAlert,
  Database,
  FileJson,
  FolderOpen,
  Layers,
  LoaderCircle,
  Plug,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "./types";
import type { Brand, Connector, TrendEngineStatus } from "./types";
import type { EditorialSource } from "./editorialTypes";
import "./sources.css";

const NETWORK: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  linkedin: "LinkedIn",
  youtube: "YouTube",
};
const KIND: Record<string, string> = {
  creator: "Búsqueda de creadores",
  trend: "Radar de tendencias",
  batch: "Lote importado",
};
const COUNT: Record<string, string> = {
  posts: "piezas",
  topics: "temas",
  candidates: "candidatos",
  results: "resultados",
};
const date = (value: string) =>
  new Date(value).toLocaleString("es", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function SourcesWorkspace({
  brand,
  onDiscover,
  onOpenEditorial,
  children,
}: {
  brand: Brand;
  onDiscover: () => void;
  onOpenEditorial: (source: string) => void;
  children: ReactNode;
}) {
  const [sources, setSources] = useState<EditorialSource[] | null>(null);
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [engine, setEngine] = useState<TrendEngineStatus | null>(null);
  const [loading, setLoading] = useState(true),
    [errors, setErrors] = useState<string[]>([]),
    [revision, setRevision] = useState(0);
  const [network, setNetwork] = useState(""),
    [kind, setKind] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    setErrors([]);
    Promise.allSettled([
      api<EditorialSource[]>(`/brands/${brand.id}/editorial-sources`),
      api<Connector[]>("/profile-connectors"),
      api<TrendEngineStatus>("/trend-engine"),
    ]).then(([saved, profiles, radar]) => {
      if (!active) return;
      const failed: string[] = [];
      if (saved.status === "fulfilled") setSources(saved.value);
      else
        failed.push(
          `Fuentes guardadas: ${saved.reason?.message || "no disponibles"}`,
        );
      if (profiles.status === "fulfilled") setConnectors(profiles.value);
      else
        failed.push(
          `Conectores: ${profiles.reason?.message || "no disponibles"}`,
        );
      if (radar.status === "fulfilled") setEngine(radar.value);
      else
        failed.push(
          `Motor LinkedIn/YouTube: ${radar.reason?.message || "no disponible"}`,
        );
      setErrors(failed);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [brand.id, revision]);
  const items = (sources || []).filter(
    (s) =>
      (!network || s.networks.includes(network)) && (!kind || s.kind === kind),
  );
  const runs = sources?.filter((s) => s.kind !== "batch").length;
  const imports = sources?.filter((s) => s.kind === "batch").length;
  const ready = sources?.filter((s) => s.progress?.ready).length;
  const demoOnly = !!sources?.length && sources.every((s) => s.demo);
  return (
    <div className="sources-workspace">
      <section className="sources-hero">
        <div>
          <div className="eyebrow">FUENTES → DESCUBRIMIENTO → INFORME</div>
          <h2>Cada señal, en su lugar.</h2>
          <p>
            Las corridas y los lotes de <strong>{brand.brief.name}</strong> se
            conectan al informe editorial desde aquí. No hace falta importar un
            JSON para usar los resultados del paso 2.
          </p>
        </div>
        <button className="button dark" onClick={onDiscover}>
          Ir al descubrimiento <ArrowRight size={16} />
        </button>
      </section>
      <div className="sources-metrics">
        <div>
          <Layers size={18} />
          <strong>{runs ?? "—"}</strong>
          <span>
            {runs === 1 ? "corrida del paso 2" : "corridas del paso 2"}
          </span>
        </div>
        <div>
          <FileJson size={18} />
          <strong>{imports ?? "—"}</strong>
          <span>{imports === 1 ? "lote guardado" : "lotes guardados"}</span>
        </div>
        <div>
          <FolderOpen size={18} />
          <strong>{ready ?? "—"}</strong>
          <span>
            {ready === 1 ? "fuente con resultados" : "fuentes con resultados"}
          </span>
        </div>
        <div>
          <Plug size={18} />
          <strong>
            {connectors
              ? `${connectors.filter((c) => c.configured).length}/4`
              : "—"}
          </strong>
          <span>conectores de perfiles configurados</span>
        </div>
      </div>
      {!!errors.length && (
        <div className="alert error" role="alert">
          <div>
            {errors.map((e) => (
              <p key={e}>{e}</p>
            ))}
          </div>
          <button onClick={() => setRevision((v) => v + 1)}>Reintentar</button>
        </div>
      )}
      <section
        className="sources-library"
        aria-label="Fuentes guardadas de la marca"
      >
        <div className="sources-heading">
          <div>
            <div className="eyebrow">LA EVIDENCIA DE TU MARCA</div>
            <h2>Fuentes guardadas</h2>
          </div>
          <button
            className="button small"
            disabled={loading}
            onClick={() => setRevision((v) => v + 1)}
            aria-label="Actualizar fuentes guardadas"
          >
            <RefreshCw size={15} className={loading ? "spin" : ""} /> Actualizar
          </button>
        </div>
        {demoOnly && (
          <div className="demo-banner">
            <ShieldCheck size={16} />
            <strong>Solo hay datos de demostración.</strong>
            <span>
              Esta marca no tiene corridas reales guardadas en esta base de
              datos.
            </span>
          </div>
        )}
        {loading && !sources && (
          <div className="sources-loading" role="status">
            <LoaderCircle size={20} className="spin" /> Consultando fuentes
            guardadas…
          </div>
        )}
        {!!sources?.length && (
          <>
            <div className="sources-filters">
              <label>
                Red
                <select
                  value={network}
                  onChange={(e) => setNetwork(e.target.value)}
                  aria-label="Filtrar fuentes por red"
                >
                  <option value="">Todas las redes</option>
                  {Object.entries(NETWORK).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Origen
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  aria-label="Filtrar fuentes por origen"
                >
                  <option value="">Todos los orígenes</option>
                  {Object.entries(KIND).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <span aria-live="polite">
                {items.length} {items.length === 1 ? "fuente" : "fuentes"}
              </span>
            </div>
            <div className="sources-cards">
              {items.map((s) => (
                <article className="source-card" key={s.id}>
                  <div className="source-card-icon">
                    {s.kind === "batch" ? (
                      <FileJson size={21} />
                    ) : (
                      <Database size={21} />
                    )}
                  </div>
                  <div className="source-card-content">
                    <div className="source-card-top">
                      <span>{KIND[s.kind] || s.kind}</span>
                      <span
                        className={`source-state ${s.demo ? "demo" : s.progress?.ready ? "ready" : "pending"}`}
                      >
                        {s.demo
                          ? "Demo sintética"
                          : s.progress?.label || "Estado guardado"}
                      </span>
                    </div>
                    <h3>{s.label}</h3>
                    <div className="source-card-meta">
                      {s.networks.map((n) => (
                        <span key={n} className={`ed-platform platform-${n}`}>
                          {NETWORK[n]}
                        </span>
                      ))}
                      <time dateTime={s.created_at}>{date(s.created_at)}</time>
                    </div>
                    <p>
                      {s.progress?.description ||
                        "Resultados guardados de esta fuente."}
                    </p>
                    <div className="source-card-bottom">
                      <div>
                        {Object.entries(s.progress?.counts || {}).map(
                          ([key, value]) => (
                            <span key={key}>
                              <strong>{value}</strong> {COUNT[key] || key}
                            </span>
                          ),
                        )}
                      </div>
                      <button
                        className="source-open"
                        onClick={() => onOpenEditorial(s.id)}
                      >
                        {s.progress?.ready
                          ? "Abrir informe"
                          : "Ver resultados guardados"}{" "}
                        <ArrowRight size={15} />
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            {!items.length && (
              <div className="sources-empty">
                <FolderOpen size={27} />
                <h3>No hay fuentes con esos filtros.</h3>
                <button
                  className="button small"
                  onClick={() => {
                    setNetwork("");
                    setKind("");
                  }}
                >
                  Limpiar filtros
                </button>
              </div>
            )}
          </>
        )}
        {!loading && sources?.length === 0 && (
          <div className="sources-empty">
            <Database size={32} />
            <h3>Aún no hay corridas ni lotes para esta marca.</h3>
            <p>
              Agregar enlaces en Identidad analiza el perfil de tu marca. Para
              encontrar tendencias, inicia una búsqueda en Descubrimiento y
              completa sus etapas; la corrida aparecerá aquí automáticamente.
            </p>
            <button className="button dark" onClick={onDiscover}>
              Buscar contenido <ArrowRight size={15} />
            </button>
          </div>
        )}
        <p className="sources-readonly">
          <ShieldCheck size={14} /> Consultar esta pantalla no inicia
          extracciones ni análisis de pago. Cada marca muestra sus propias
          fuentes.
        </p>
      </section>
      <section aria-label="Configuración de conectores">
        <div className="sources-heading">
          <div>
            <div className="eyebrow">ACCESO A LOS PROVEEDORES</div>
            <h2>
              Conectores de perfiles <small>paso 01</small>
            </h2>
          </div>
          <p>
            Configuración presente en el servidor. No es una prueba de acceso,
            saldo o permisos.
          </p>
        </div>
        <div className="sources-connectors">
          {(connectors || []).map((c) => {
            const links = brand.brief.profiles.filter(
              (p) => p.platform === c.platform,
            ).length;
            return (
              <article className="source-connector" key={c.platform}>
                <div>
                  <span className={`network-mark net-${c.platform}`}>
                    {c.platform === "instagram"
                      ? "IG"
                      : c.platform === "linkedin"
                        ? "in"
                        : c.platform === "tiktok"
                          ? "TT"
                          : "YT"}
                  </span>
                  <strong>{NETWORK[c.platform]}</strong>
                </div>
                <span
                  className={`source-config-status ${c.configured ? "configured" : "missing"}`}
                >
                  {c.configured ? (
                    <Check size={13} />
                  ) : (
                    <CircleAlert size={13} />
                  )}
                  {c.configured ? "Configuración presente" : "Por configurar"}
                </span>
                <p>
                  {links
                    ? `${links} enlace${links > 1 ? "s" : ""} de esta marca`
                    : "Sin enlaces en esta marca"}
                </p>
                <small>
                  {c.primary?.configured
                    ? "Bright Data como proveedor principal"
                    : c.fallback?.configured
                      ? "API oficial de respaldo disponible"
                      : "Configurar credenciales en el servidor"}
                </small>
                {!!c.missing.length && (
                  <details>
                    <summary>Qué falta configurar</summary>
                    <ul>
                      {c.missing.map((key) => (
                        <li key={key}>
                          <code>{key}</code>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </article>
            );
          })}
        </div>
        {engine && (
          <div className="sources-engine">
            <div>
              <strong>
                Radar LinkedIn + YouTube <small>paso 02</small>
              </strong>
              <p>
                La búsqueda de tendencias usa su propia configuración, además de
                los conectores de perfiles.
              </p>
            </div>
            <span
              className={`source-config-status ${engine.configured ? "configured" : "missing"}`}
            >
              {engine.configured
                ? "Configuración presente"
                : "Configuración pendiente"}
            </span>
            {!!engine.missing.length && (
              <details>
                <summary>Variables pendientes</summary>
                <ul>
                  {engine.missing.map((key) => (
                    <li key={key}>
                      <code>{key}</code>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </section>
      <details className="sources-manual">
        <summary>
          <FileJson size={19} />
          <span>
            <strong>Importar un lote externo</strong>
            <small>Opción avanzada · archivo JSON de otro recolector</small>
          </span>
          <span>Abrir importador</span>
        </summary>
        <div className="sources-manual-body">{children}</div>
      </details>
    </div>
  );
}
