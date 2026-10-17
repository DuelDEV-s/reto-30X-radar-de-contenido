import { ArrowUpRight } from "lucide-react";
import type { InterpretationEvidence, ProfileAnalysis } from "./types";

function Evidence({ items }: { items: InterpretationEvidence[] }) {
  return (
    <details className="interpretation-evidence">
      <summary>Ver evidencia textual</summary>
      {items.map((e, i) => (
        <div key={i}>
          <blockquote>{e.excerpt}</blockquote>
          {e.source_url ? (
            <a href={e.source_url} target="_blank" rel="noopener noreferrer">
              {e.source_kind === "post"
                ? "Publicación de referencia"
                : e.source_kind === "manual"
                  ? "Contexto manual asociado al perfil"
                  : "Perfil de referencia"}{" "}
              <ArrowUpRight size={12} />
            </a>
          ) : (
            <small>Contexto aportado por el equipo</small>
          )}
        </div>
      ))}
    </details>
  );
}

export default function InterpretationPanel({
  data,
}: {
  data: ProfileAnalysis;
}) {
  const detail = data.interpretation;
  if (!detail)
    return (
      <p className="muted">
        Reinterpreta los datos guardados para generar una propuesta con
        evidencia.
      </p>
    );
  const c = detail.coverage;
  return (
    <div className="interpretation-panel">
      <div className="interpretation-context">
        <span className="pill green">LECTURA DE LA MARCA</span>
        <p>
          {c.usable_profiles} perfiles habilitados · {c.sample_size} piezas ·{" "}
          {c.unique_texts} textos distintos
        </p>
        {data.interpreted_at && (
          <small>
            Interpretación actualizada:{" "}
            {new Date(data.interpreted_at).toLocaleString("es")}. Las fechas de
            las fuentes se conservan.
          </small>
        )}
      </div>
      {!!detail.facts.length && (
        <div className="interpretation-facts">
          {detail.facts.map((fact) => (
            <article key={fact.label}>
              <small>{fact.label}</small>
              <h3>{fact.value}</h3>
              <Evidence items={fact.evidence} />
            </article>
          ))}
        </div>
      )}
      <h3>Pilares de contenido propuestos</h3>
      <p className="muted">
        Ideas basadas en lo que comunica la marca. Cada experimento requiere
        medir su resultado.
      </p>
      <div className="interpretation-pillars">
        {detail.pillars.map((pillar) => (
          <article key={pillar.topic}>
            <h4>{pillar.topic}</h4>
            <p>{pillar.idea}</p>
            <small>{pillar.rationale}</small>
            <p className="interpretation-measure">
              <strong>Qué medir:</strong> {pillar.measurement}
            </p>
            <Evidence items={pillar.evidence} />
          </article>
        ))}
      </div>
      {!!detail.audience_hypotheses.length && (
        <>
          <h3>Audiencias por validar</h3>
          <p className="muted">
            Hipótesis a partir de las ocasiones y servicios mencionados; no
            describen compradores observados.
          </p>
          <div className="interpretation-facts">
            {detail.audience_hypotheses.map((h) => (
              <article key={h.role}>
                <h4>{h.role}</h4>
                <p>{h.need}</p>
                <Evidence items={h.evidence} />
              </article>
            ))}
          </div>
        </>
      )}
      <details className="interpretation-limits" open>
        <summary>Alcance y datos que faltan</summary>
        <ul>
          {detail.limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
