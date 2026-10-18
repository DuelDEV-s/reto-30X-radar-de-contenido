import { useState } from "react";
import { ArrowRight, NotebookPen } from "lucide-react";
import type { Brand, BrandContext } from "./types";

export default function BrandContextForm({ brand, busy, onSave }: {
  brand: Brand; busy: boolean; onSave: (context: BrandContext) => void;
}) {
  const [description, setDescription] = useState(brand.brief.description || "");
  const [audience, setAudience] = useState(brand.brief.audience || "");
  const [topics, setTopics] = useState((brand.brief.topics || []).join(", "));
  const [editing, setEditing] = useState(!description || !audience);
  return (
    <section className="brand-context-form" aria-label="Contexto para crear personas">
      <div className="persona-section-heading">
        <div>
          <div className="eyebrow"><NotebookPen size={14} /> CONTEXTO DEL EQUIPO</div>
          <h3>Una persona útil empieza por una propuesta clara.</h3>
          <p>Complementa lo que la red no cuenta. Se guarda como información declarada por tu equipo, separada de las observaciones del perfil.</p>
        </div>
        <button className="button small" onClick={() => setEditing(!editing)} aria-expanded={editing}>
          {editing ? "Ocultar formulario" : "Editar contexto"}
        </button>
      </div>
      {editing && <form onSubmit={(e) => {
        e.preventDefault();
        onSave({ description, audience, topics: topics.split(",").map(t => t.trim()).filter(Boolean) });
      }}>
        <label>¿Qué publica u ofrece la marca?
          <textarea rows={3} minLength={20} maxLength={5000} value={description} onChange={e => setDescription(e.target.value)} placeholder="Temas, propuesta de valor y qué hace distinta a la cuenta." />
        </label>
        <label>¿A quién quiere llegar?
          <input minLength={5} maxLength={1000} value={audience} onChange={e => setAudience(e.target.value)} placeholder="Intereses o necesidades de la audiencia que quieren atender." />
        </label>
        <label>Temas específicos, separados por comas
          <input maxLength={1500} value={topics} onChange={e => setTopics(e.target.value)} placeholder="Por ejemplo: series de animación, Gravity Falls" />
        </label>
        <div className="form-actions">
          <button className="button dark" disabled={busy}>Guardar contexto y generar personas <ArrowRight size={15} /></button>
          <small>Usa datos guardados. No inicia extracciones ni llamadas a modelos. La identidad actual se conserva hasta que apliques la propuesta.</small>
        </div>
      </form>}
    </section>
  );
}
