import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import type { Brand, TrendPlatform } from "./types";
import DiscoveryPanel from "./DiscoveryPanel";
import TrendRadarPanel from "./TrendRadarPanel";

type Network = "instagram" | "tiktok" | TrendPlatform;

const NETWORKS: { id: Network; label: string; mark: string; engine: string; note: string; available: boolean }[] = [
  { id: "instagram", label: "Instagram", mark: "IG", engine: "Creadores", note: "Cuentas que publican sobre el tópico · SERP + revisión LLM", available: true },
  { id: "linkedin", label: "LinkedIn", mark: "in", engine: "Radar de tendencias", note: "Qué se publica y dónde hay hueco · Exa + Claude", available: true },
  { id: "youtube", label: "YouTube", mark: "YT", engine: "Radar de tendencias", note: "Qué premia la audiencia · YouTube Data API", available: true },
  { id: "tiktok", label: "TikTok", mark: "TT", engine: "Próximamente", note: "Aún sin conector", available: false },
];
const STORAGE_KEY = "radar-discovery-networks";

function initialSelection(): Network[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (Array.isArray(saved) && saved.length) return saved;
  } catch {
    /* Sin almacenamiento disponible: se usa la red por defecto. */
  }
  return ["instagram"];
}

/** Paso 2: elige la red y muestra el mecanismo de descubrimiento que la cubre.
 * Instagram usa la búsqueda de creadores; LinkedIn y YouTube, el radar de tendencias (combinables). */
export default function DiscoveryWorkspace({ brand, onOpenBatch }: { brand: Brand; onOpenBatch: (batchId: string) => void }) {
  const [selected, setSelected] = useState<Network[]>(initialSelection);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch {
      /* La selección solo dura la sesión. */
    }
  }, [selected]);

  function toggle(id: Network) {
    setSelected((current) => {
      if (id === "instagram") return ["instagram"];
      const trends = current.filter((n): n is TrendPlatform => n === "linkedin" || n === "youtube");
      if (trends.includes(id as TrendPlatform)) return trends.length > 1 ? trends.filter((n) => n !== id) : trends;
      return [...trends, id as TrendPlatform];
    });
  }

  const trendPlatforms = selected.filter((n): n is TrendPlatform => n === "linkedin" || n === "youtube");
  return (
    <div className="discovery-workspace">
      <section className="network-picker" aria-label="Red social para descubrir">
        <div className="network-picker-head">
          <div className="eyebrow">PASO 02 · ¿DÓNDE BUSCAMOS?</div>
          <p className="muted">LinkedIn y YouTube se pueden combinar en un mismo radar. Instagram usa su propia búsqueda de creadores.</p>
        </div>
        <div className="network-options" role="group">
          {NETWORKS.map((n) => {
            const active = selected.includes(n.id);
            return (
              <button
                key={n.id}
                type="button"
                className={`network-option${active ? " active" : ""}`}
                aria-pressed={active}
                disabled={!n.available}
                onClick={() => toggle(n.id)}
              >
                <span className="network-option-check">{active && <Check size={12} />}</span>
                <span className={`network-mark net-${n.id}`} aria-hidden="true">{n.mark}</span>
                <span className="network-option-text">
                  <strong>{n.label}</strong>
                  <small>{n.engine}</small>
                  <span>{n.note}</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>
      {trendPlatforms.length ? (
        <TrendRadarPanel brand={brand} platforms={trendPlatforms} onOpenBatch={onOpenBatch} />
      ) : (
        <DiscoveryPanel brand={brand} />
      )}
    </div>
  );
}
