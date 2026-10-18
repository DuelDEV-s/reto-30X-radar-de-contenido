import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  Download,
  LoaderCircle,
  Radar,
  RefreshCw,
} from "lucide-react";
import type { Brand, SocialProfile } from "./types";
import InterpretationPanel from "./InterpretationPanel";

const names: Record<string, string> = {
  instagram: "Instagram",
  youtube: "YouTube",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
};
const states: Record<string, string> = {
  ready: "Consultado",
  pending: "Recolectando…",
  requires_configuration: "Falta configurar",
  unsupported: "Sin conector disponible",
  not_found: "No encontrado",
  error: "Consulta fallida",
};
const metric = (value: number | null) =>
  value === null ? "No disponible" : new Intl.NumberFormat("es").format(value);

export default function ProfileAnalysisPanel({
  brand,
  busy,
  onAnalyze,
  onInterpret,
}: {
  brand: Brand;
  busy: boolean;
  onAnalyze: (
    profiles: SocialProfile[],
    apply: boolean,
    force: boolean,
    refreshBrightData?: boolean,
  ) => void;
  onInterpret: (apply: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [profiles, setProfiles] = useState(brand.brief.profiles);
  const [confirmed, setConfirmed] = useState(false);
  const data = brand.profile_analysis;
  const canEnrich =
    !!data &&
    (data.identity_evidence.length > 0 ||
      data.profiles.some((p) => p.supplied_description));
  function setProfile(platform: string, url: string) {
    setProfiles((items) => {
      const previous = items.find((x) => x.platform === platform);
      const rest = items.filter((x) => x.platform !== platform);
      return url.trim()
        ? [...rest, { platform, url, description: previous?.description || "" }]
        : rest;
    });
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "brand-profile-analysis.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="panel profile-analysis-panel">
      <div className="profile-panel-heading">
        <div>
          <div className="eyebrow">PASO 01 · OBSERVACIÓN DE PERFILES</div>
          <h2>De tus redes a tu identidad.</h2>
          <p>
            Descripción, contadores y contenido público disponible. Cada dato
            conserva su origen. Bright Data es la fuente principal; Meta y
            YouTube quedan como respaldo.
          </p>
        </div>
        <Radar size={32} />
      </div>
      <div className="form-actions">
        <button
          className="button"
          disabled={busy}
          onClick={() => setEditing(!editing)}
        >
          {editing ? "Ocultar enlaces" : "Editar redes sociales"}
        </button>
        <button
          className="button dark"
          disabled={busy || !brand.brief.profiles.length}
          onClick={() => onAnalyze(brand.brief.profiles, false, true)}
        >
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <RefreshCw size={16} />
          )}{" "}
          Consultar análisis
        </button>
      </div>
      {!!data && (
        <div className="form-actions">
          <button
            className="button"
            disabled={busy}
            onClick={() => onInterpret(false)}
          >
            Reinterpretar datos guardados
          </button>
          <small>
            Usa la información disponible, sin consultar proveedores ni consumir
            créditos de extracción.
          </small>
        </div>
      )}
      {data?.profiles.some((p) => p.collection) && (
        <div className="form-actions">
          <button
            className="button"
            disabled={busy || data.status === "pending"}
            onClick={() => onAnalyze(brand.brief.profiles, false, true, true)}
          >
            Nueva recolección
          </button>
          <small>
            Inicia otro trabajo en Bright Data y puede consumir créditos.
            Consultar análisis reutiliza el trabajo guardado.
          </small>
        </div>
      )}
      {data?.status === "pending" && (
        <p className="alert" role="status">
          <LoaderCircle className="spin" size={16} />
          Recolección en curso. Los resultados se actualizan automáticamente sin
          iniciar otra extracción.
        </p>
      )}
      {editing && (
        <form
          className="profile-link-form"
          onSubmit={(e) => {
            e.preventDefault();
            onAnalyze(profiles, false, true);
          }}
        >
          {Object.entries(names).map(([key, name]) => (
            <label key={key}>
              {name}
              <input
                type="url"
                placeholder={
                  key === "youtube" || key === "tiktok"
                    ? `https://www.${key}.com/@${key === "tiktok" ? "tu_marca" : "tu-marca"}`
                    : key === "linkedin"
                      ? "https://www.linkedin.com/company/tu-marca"
                      : "https://www.instagram.com/tu-marca"
                }
                value={profiles.find((x) => x.platform === key)?.url || ""}
                onChange={(e) => setProfile(key, e.target.value)}
                maxLength={500}
              />
            </label>
          ))}
          <label className="checkbox-label">
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Confirmo que son cuentas públicas de la marca, sin perfiles
            personales.
          </label>
          <button className="button dark" disabled={busy || !confirmed}>
            Guardar enlaces y analizar
          </button>
        </form>
      )}
      {!data ? (
        <p className="muted">
          Agrega los perfiles de tu marca y analízalos. No se modifica una
          identidad confirmada sin que apliques la propuesta.
        </p>
      ) : (
        <>
          <div className="analysis-stamp">
            <span>{new Date(data.analyzed_at).toLocaleString("es")}</span>
            <span>
              {data.stale
                ? "Consulta antigua · puedes actualizar"
                : "Último resultado guardado"}
            </span>
            <button className="button small" onClick={download}>
              <Download size={14} /> Exportar JSON
            </button>
          </div>
          <div className="profile-results">
            {data.profiles.map((p) => (
              <article key={p.url} className="profile-result">
                <div className="profile-result-title">
                  <a href={p.url} target="_blank" rel="noopener noreferrer">
                    {names[p.platform]} <ArrowUpRight size={14} />
                  </a>
                  <span
                    className={p.status === "ready" ? "pill green" : "pill"}
                  >
                    {states[p.status] || p.status}
                  </span>
                </div>
                <p className="profile-message">{p.message}</p>
                {!!p.attempts?.length && (
                  <details>
                    <summary>
                      {p.fallback_used
                        ? "Se utilizó el respaldo oficial"
                        : "Estado de los proveedores"}
                    </summary>
                    {p.attempts.map((a, i) => (
                      <p className="muted" key={i}>
                        {a.provider}: {states[a.status] || a.status}.{" "}
                        {a.message}
                      </p>
                    ))}
                  </details>
                )}
                {p.collection && (
                  <p className="muted">
                    Recolección: {p.collection.state}
                    {p.collection.snapshot_id
                      ? ` · ${p.collection.snapshot_id}`
                      : ""}
                  </p>
                )}
                {p.status === "ready" && (
                  <>
                    <h3>{p.title || "Descripción pública"}</h3>
                    <p>
                      {p.description || "La fuente no entregó descripción."}
                    </p>
                    <div className="profile-metrics">
                      <div>
                        <small>Vistas acumuladas</small>
                        <strong>{metric(p.metrics.views)}</strong>
                      </div>
                      <div>
                        <small>Seguidores / suscriptores</small>
                        <strong>{metric(p.metrics.followers)}</strong>
                      </div>
                      <div>
                        <small>Publicaciones</small>
                        <strong>{metric(p.metrics.posts)}</strong>
                      </div>
                    </div>
                    {p.metrics_notes.map((note) => (
                      <p className="muted" key={note}>
                        {note}
                      </p>
                    ))}
                    {!!p.content_sample.length && (
                      <details>
                        <summary>
                          {p.content_sample.length} piezas públicas de la
                          muestra
                        </summary>
                        {p.content_sample.map((c) => (
                          <div className="profile-sample" key={c.url}>
                            <a
                              href={c.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {c.title || "Ver publicación"}{" "}
                              <ArrowUpRight size={12} />
                            </a>
                            <small>
                              {c.format} ·{" "}
                              {c.views === null
                                ? "Vistas no disponibles"
                                : `${metric(c.views)} vistas`}
                            </small>
                          </div>
                        ))}
                      </details>
                    )}
                  </>
                )}
                <small className="profile-provider">
                  Fuente: {p.provider} ·{" "}
                  {new Date(p.observed_at).toLocaleString("es")} ·{" "}
                  {p.usable_for_identity
                    ? "Texto disponible para enriquecer la identidad"
                    : "Sin uso automático en la identidad"}
                </small>
              </article>
            ))}
          </div>
          <div className="analysis-proposal">
            <div className="eyebrow">
              {canEnrich
                ? "PROPUESTA A PARTIR DE LA EVIDENCIA"
                : "IDENTIDAD PENDIENTE DE FUENTES"}
            </div>
            <div className="tags">
              {data.suggested_identity.topics.map((t) => (
                <span key={t}>{t}</span>
              ))}
            </div>
            <p>{data.suggested_identity.summary}</p>
            <p className="muted">{data.method}</p>
            <InterpretationPanel data={data} />
            <button
              className="button dark"
              disabled={busy || !canEnrich}
              onClick={() => onInterpret(true)}
            >
              <Check size={16} /> Usar propuesta como borrador
            </button>
          </div>
          {!data.interpretation && (
            <div className="profile-opportunities">
              <h3>Cómo potenciar el perfil</h3>
              {data.opportunities.map((o, i) => (
                <div key={i}>
                  <strong>{names[o.platform]}</strong>
                  <p>{o.action}</p>
                  <small>{o.basis}</small>
                </div>
              ))}
            </div>
          )}
          <details>
            <summary>Ver JSON estructurado del análisis</summary>
            <pre className="analysis-json">{JSON.stringify(data, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
