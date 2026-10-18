import { ArrowUpRight, UsersRound, ClipboardCheck } from "lucide-react";
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
  const readiness = {
    needs_context: "Falta contexto para definir personas específicas",
    exploratory: "Primeras personas exploratorias",
    text_supported: "Personas propuestas con respaldo textual",
  };
  const basis = { declared: "Contexto del equipo", textual: "Señal en los textos", exploratory: "Hipótesis exploratoria", team: "Edición del equipo" };
  const platforms: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram", youtube: "YouTube", linkedin: "LinkedIn" };
  const amount = (n: number | null) => n === null ? "Sin datos" : n.toLocaleString("es", { maximumFractionDigits: 1 });
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
      <section className="audience-readiness" aria-label="Respaldo de las personas propuestas">
        <UsersRound size={23} aria-hidden="true" />
        <div>
          <strong>{readiness[detail.audience_readiness || (detail.audience_hypotheses.length ? "text_supported" : "needs_context")]}</strong>
          <p>Los intereses, necesidades y barreras se proponen para probar contenido. No representan la demografía ni los compradores reales de la cuenta.</p>
          {!!detail.missing_context?.length && <details><summary>Qué falta para afinar esta lectura</summary><ul>{detail.missing_context.map(item => <li key={item}>{item}</li>)}</ul></details>}
        </div>
      </section>
      {!!detail.audience_hypotheses.length && (
        <section aria-label="User personas propuestas">
          <div className="persona-section-heading">
            <div><div className="eyebrow">USER PERSONAS · PROPUESTAS</div><h3>De los intereses a una idea que puedas probar.</h3></div>
            <span className="pill">{detail.audience_hypotheses.length} segmentos</span>
          </div>
          <div className="audience-personas">
            {detail.audience_hypotheses.map((h, i) => (
              <article className="audience-persona" key={h.role}>
                <div className="persona-card-top"><span className="persona-number">{String(i + 1).padStart(2, "0")}</span><span className="pill">{basis[h.basis || "textual"]}</span></div>
                <h4>{h.role}</h4>
                <p>{h.need}</p>
                <dl className="persona-attributes">
                  {h.goal && <div><dt>Qué busca lograr</dt><dd>{h.goal}</dd></div>}
                  {!!h.barriers?.length && <div><dt>Barreras a comprobar</dt><dd><ul>{h.barriers.map(v => <li key={v}>{v}</li>)}</ul></dd></div>}
                  {!!h.content_angles?.length && <div><dt>Ideas para este segmento</dt><dd><ul>{h.content_angles.map(v => <li key={v}>{v}</li>)}</ul></dd></div>}
                </dl>
                {h.validation_question && <div className="persona-validation"><ClipboardCheck size={17} /><div><strong>Pregunta para validar</strong><p>{h.validation_question}</p></div></div>}
                <Evidence items={h.evidence} />
              </article>
            ))}
          </div>
        </section>
      )}
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
      {!!detail.content_snapshot?.length && <section aria-label="Lectura de la muestra de contenido">
        <h3>Lo que sí sabemos del contenido</h3>
        <p className="muted">Resumen de las piezas incluidas en el análisis. La mediana y los enlaces corresponden solo a esta muestra; no indican crecimiento ni rendimiento habitual.</p>
        <div className="interpretation-facts">{detail.content_snapshot.map(s => <article key={s.platform}>
          <h4>{platforms[s.platform]}</h4>
          <div className="sample-summary-stats"><div><small>Piezas analizadas</small><strong>{s.sample_size}</strong></div><div><small>Con vistas conocidas</small><strong>{s.with_views}</strong></div><div><small>Mediana de vistas</small><strong>{amount(s.median_views)}</strong></div></div>
          {s.sample_size === 0 ? <p>El perfil no incluyó publicaciones para leer. Su contador de videos no equivale a videos analizados.</p> : <>
            <p>Formatos observados: {s.formats.join(", ") || "no informados"}.</p>
            {s.latest_published_at && <small>Publicación más reciente de la muestra: {new Date(s.latest_published_at).toLocaleDateString("es")}</small>}
            {!!s.top_content.length && <><h4>Mayores vistas de la muestra</h4>{s.top_content.map(post => <div className="sample-highlight" key={post.url}><a href={post.url} target="_blank" rel="noopener noreferrer">{post.title} <ArrowUpRight size={12} /></a><small>{amount(post.views)} vistas observadas</small></div>)}</>}
          </>}
        </article>)}</div>
      </section>}
      {!!detail.next_steps?.length && <section aria-label="Próximas acciones del perfil"><h3>Cómo fortalecer este perfil</h3><div className="profile-next-steps">{detail.next_steps.map((s, i) => <article key={s.title}><span>{String(i + 1).padStart(2, "0")}</span><div><h4>{s.title}</h4><p>{s.action}</p><small>{s.reason}</small></div></article>)}</div></section>}
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
