import { useState } from "react";
import { ArrowUpRight, Play, X, Clapperboard } from "lucide-react";
import type { Preview } from "./editorialTypes";

export function publicMedia(url: string): Preview {
  const empty = { embed_url: null, platform: null, orientation: "landscape" };
  try {
    const u = new URL(url);
    if (
      u.protocol !== "https:" ||
      u.username ||
      u.password ||
      (u.port && u.port !== "443")
    )
      return empty;
    let id: string | null = null;
    if (
      ["www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be"].includes(
        u.hostname,
      )
    ) {
      id =
        u.hostname === "youtu.be"
          ? u.pathname.slice(1)
          : u.pathname.startsWith("/shorts/")
            ? u.pathname.split("/")[2]
            : u.searchParams.get("v");
      if (id && /^[\w-]{11}$/.test(id))
        return {
          embed_url: `https://www.youtube-nocookie.com/embed/${id}?autoplay=0`,
          platform: "youtube",
          orientation: u.pathname.startsWith("/shorts/")
            ? "portrait"
            : "landscape",
        };
    }
    const ig = u.pathname.match(/^\/(reel|p)\/([\w-]{1,64})\/?$/);
    if (["www.instagram.com", "instagram.com"].includes(u.hostname) && ig)
      return {
        embed_url: `https://www.instagram.com/${ig[1]}/${ig[2]}/embed/`,
        platform: "instagram",
        orientation: "portrait",
      };
    const tt = u.pathname.match(/^\/@[\w.]+\/video\/(\d{15,25})\/?$/);
    if (["www.tiktok.com", "tiktok.com"].includes(u.hostname) && tt)
      return {
        embed_url: `https://www.tiktok.com/player/v1/${tt[1]}?autoplay=0`,
        platform: "tiktok",
        orientation: "portrait",
      };
    const li =
      u.pathname.match(/^\/feed\/update\/urn:li:activity:(\d{15,25})\/?$/) ||
      u.pathname.match(/^\/posts\/[^/]+-activity-(\d{15,25})-[^/]+\/?$/);
    if (["www.linkedin.com", "linkedin.com"].includes(u.hostname) && li)
      return {
        embed_url: `https://www.linkedin.com/embed/feed/update/urn:li:activity:${li[1]}`,
        platform: "linkedin",
        orientation: "portrait",
      };
  } catch {
    /* Invalid or unsupported URLs stay as source links. */
  }
  return empty;
}

/** No third-party requests until the reader explicitly opens a preview. */
export default function MediaPreview({
  url,
  title,
  descriptor,
  demo = false,
  compact = false,
}: {
  url: string | null;
  title: string;
  descriptor?: Preview;
  demo?: boolean;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const media = demo ? null : descriptor || publicMedia(url || "");
  const src = media?.embed_url;
  if (!src)
    return (
      <div className="media-unavailable">
        <Clapperboard size={16} />
        <span>
          {demo ? "Pieza sintética · sin video real" : "Preview no disponible"}
        </span>
      </div>
    );
  return (
    <div
      className={`media-preview ${compact ? "compact" : ""} ${open ? "is-open" : ""}`}
    >
      {!open ? (
        <button
          className="media-launch"
          onClick={() => setOpen(true)}
          aria-label={`Ver preview: ${title}`}
        >
          <span className="media-play">
            <Play size={20} fill="currentColor" />
          </span>
          <span>
            <strong>Ver la pieza</strong>
            <small>Reproductor de {media.platform} · sin autoplay</small>
          </span>
          <Clapperboard size={23} className="media-watermark" />
        </button>
      ) : (
        <>
          <div className="media-toolbar">
            <span>Preview de {media.platform}</span>
            <button onClick={() => setOpen(false)} aria-label="Cerrar preview">
              <X size={15} />
            </button>
          </div>
          <iframe
            src={src}
            title={`Preview: ${title}`}
            loading="lazy"
            className={
              media.orientation === "portrait" ? "portrait" : "landscape"
            }
            allow="encrypted-media; fullscreen; picture-in-picture"
            referrerPolicy="strict-origin-when-cross-origin"
            sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"
            allowFullScreen
          />
          <p className="media-help">
            Si la plataforma bloquea la reproducción,{" "}
            <a href={url || "#"} target="_blank" rel="noreferrer">
              abre la publicación <ArrowUpRight size={11} />
            </a>
            .
          </p>
        </>
      )}
    </div>
  );
}
