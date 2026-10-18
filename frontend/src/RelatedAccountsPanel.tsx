import { useEffect, useState } from "react";
import { ArrowUpRight, BadgeCheck, LoaderCircle, Users } from "lucide-react";
import { api } from "./types";
import type { Brand, RelatedAccount, RelatedAccounts } from "./types";

const PENDING = new Set([
  "reels_requesting",
  "reels_pending",
  "profiles_requesting",
  "profiles_pending",
]);
const steps: Record<string, string> = {
  reels_requesting: "Iniciando la búsqueda de reels…",
  reels_pending: "Bright Data revisa los últimos reels de la marca (paso 1 de 2)…",
  profiles_requesting: "Iniciando la recolección de perfiles…",
  profiles_pending: "Bright Data recolecta los perfiles relacionados (paso 2 de 2)…",
};
const relationLabels: Record<RelatedAccount["relations"][number], string> = {
  coauthor: "Coautor",
  tagged: "Etiquetado",
  posted: "Publicó colaboración",
};
const compact = (n: number | null) =>
  n === null
    ? "—"
    : new Intl.NumberFormat("es", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(n);

function AccountCard({ account }: { account: RelatedAccount }) {
  const name = account.full_name || account.username;
  return (
    <article className="related-account">
      <div className="related-account-head">
        {account.avatar_url ? (
          <img src={account.avatar_url} alt="" loading="lazy" />
        ) : (
          <span className="related-account-initial">
            {name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <div>
          <strong>
            {name}
            {account.is_verified && <BadgeCheck size={13} />}
          </strong>
          <a href={account.profile_url} target="_blank" rel="noopener noreferrer">
            @{account.username} <ArrowUpRight size={11} />
          </a>
        </div>
      </div>
      <div className="related-account-pills">
        {account.relations.map((r) => (
          <span key={r} className="pill">
            {relationLabels[r]}
          </span>
        ))}
        {account.category && <span className="pill green">{account.category}</span>}
      </div>
      {account.profile_available ? (
        <>
          <div className="related-account-metrics">
            <span>
              <strong>{compact(account.followers)}</strong> seguidores
            </span>
            <span>
              <strong>{compact(account.posts_count)}</strong> posts
            </span>
            <span>
              <strong>{compact(account.following)}</strong> seguidos
            </span>
          </div>
          {account.biography && <p>{account.biography}</p>}
        </>
      ) : (
        <p className="muted">Bright Data no devolvió la ficha de este perfil.</p>
      )}
      <small>
        Aparece en {account.reel_urls.length}{" "}
        {account.reel_urls.length === 1 ? "reel" : "reels"} de la marca:{" "}
        {account.reel_urls.map((url, i) => (
          <a key={url} href={url} target="_blank" rel="noopener noreferrer">
            {i + 1}
          </a>
        ))}
      </small>
    </article>
  );
}

export default function RelatedAccountsPanel({ brand }: { brand: Brand }) {
  const [data, setData] = useState<RelatedAccounts | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const hasInstagram = brand.brief.profiles.some((p) => p.platform === "instagram");
  const pending = !!data && PENDING.has(data.state);
  const path = `/brands/${brand.id}/related-accounts`;

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    api<RelatedAccounts>(path, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      });
    return () => controller.abort();
  }, [path]);

  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    // Consulta cada 10 s mientras dure el trabajo; el GET nunca inicia otra extracción.
    const timer = setInterval(() => {
      api<RelatedAccounts>(path, { signal: controller.signal })
        .then(setData)
        .catch((e) => {
          if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
        });
    }, 10000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [path, pending]);

  async function start() {
    setStarting(true);
    setError("");
    try {
      setData(await api<RelatedAccounts>(path, { method: "POST", body: "{}" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="panel related-accounts-panel">
      <div className="profile-panel-heading">
        <div>
          <div className="eyebrow">CUENTAS RELACIONADAS · INSTAGRAM</div>
          <h2>Con quién colabora la marca</h2>
          <p className="muted">
            Cuentas que publican colaboraciones con la marca, son coautoras o
            aparecen etiquetadas en sus últimos reels. Cada búsqueda usa unos 15
            registros de Bright Data y tarda varios minutos.
          </p>
        </div>
        <Users size={22} />
      </div>
      {!hasInstagram ? (
        <p className="muted">
          Agrega el perfil de Instagram de la marca para buscar cuentas
          relacionadas.
        </p>
      ) : (
        <div className="analysis-stamp">
          {pending ? (
            <span>
              <LoaderCircle size={12} className="spin" /> {steps[data!.state]}
            </span>
          ) : data?.state === "ready" ? (
            <span>
              {data.message} Actualizado:{" "}
              {new Date(data.updated_at!).toLocaleString("es")}
            </span>
          ) : data && data.state !== "not_started" ? (
            <span>{data.message}</span>
          ) : (
            <span>Aún no se han buscado cuentas relacionadas.</span>
          )}
          <button
            className="button small dark"
            onClick={start}
            disabled={starting || pending || !data}
          >
            {data?.state === "not_started" ? "Buscar cuentas relacionadas" : "Volver a buscar"}
          </button>
        </div>
      )}
      {error && <p className="profile-message">{error}</p>}
      {!!data?.accounts.length && (
        <div className="related-accounts">
          {data.accounts.map((a) => (
            <AccountCard key={a.username} account={a} />
          ))}
        </div>
      )}
    </section>
  );
}
