import { useEffect, useRef, useState } from "react";
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
          : u.pathname.startsWith("/shorts/") || u.pathname.startsWith("/embed/")
            ? u.pathname.split("/")[2]
            : u.searchParams.get("v");
      if (id && /^[\w-]{11}$/.test(id))
        return {
          embed_url: `https://www.youtube-nocookie.com/embed/${id}?autoplay=0`,
          thumbnail_url: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
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

const IMAGE_HOSTS: Record<string, string[]> = {
  youtube: ["ytimg.com", "img.youtube.com"],
  instagram: ["cdninstagram.com", "fbcdn.net"],
  tiktok: ["tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "ibytedtos.com", "byteoversea.com"],
  linkedin: ["licdn.com"],
};

function safeThumbnail(value: string | null | undefined, platform: string | null) {
  if (!value || !platform) return null;
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !u.username && !u.password && (!u.port || u.port === "443") &&
      IMAGE_HOSTS[platform]?.some(host => u.hostname === host || u.hostname.endsWith(`.${host}`)) ? value : null;
  } catch { return null; }
}

/** Visible poster first; an official paused embed is the fallback when no image exists. */
export default function MediaPreview({
  url,
  title,
  descriptor,
  demo = false,
  compact = false,
  thumbnailUrl,
}: {
  url: string | null;
  title: string;
  descriptor?: Preview;
  demo?: boolean;
  compact?: boolean;
  thumbnailUrl?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const [nearViewport,setNearViewport] = useState(false);
  const [failedPoster, setFailedPoster] = useState<string | null>(null);
  // Always reconstruct the player from the public source URL, never provider HTML.
  const media = demo ? null : publicMedia(url || "");
  const src = media?.embed_url;
  const poster = safeThumbnail(thumbnailUrl || descriptor?.thumbnail_url || media?.thumbnail_url, media?.platform || null);
  const hasPoster = !!poster && failedPoster !== poster;
  const playerVisible = open || !hasPoster;
  useEffect(()=>{
    if (!src || hasPoster) return;
    if (!("IntersectionObserver" in window)) { setNearViewport(true); return; }
    const observer=new IntersectionObserver(entries=>{
      if(entries.some(entry=>entry.isIntersecting)){setNearViewport(true);observer.disconnect();}
    },{rootMargin:"160px"});
    if(container.current) observer.observe(container.current);
    return ()=>observer.disconnect();
  },[src,hasPoster]);
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
      ref={container}
      className={`media-preview ${compact ? "compact" : ""} ${playerVisible ? "is-open" : ""}`}
    >
      {!playerVisible ? (
        <button
          className={`media-launch has-poster ${media.orientation}`}
          onClick={() => setOpen(true)}
          aria-label={`Ver preview: ${title}`}
        >
          <img className="media-poster" src={poster!} alt={`Miniatura: ${title}`} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailedPoster(poster)} />
          <span className="media-play">
            <Play size={20} fill="currentColor" />
          </span>
          <span className="media-poster-caption">
            <strong>Ver la pieza</strong>
            <small>Reproductor de {media.platform} · sin autoplay</small>
          </span>
        </button>
      ) : (
        <>
          <div className="media-toolbar">
            <span>Preview de {media.platform}</span>
            {hasPoster && <button onClick={() => setOpen(false)} aria-label="Volver a la miniatura">
              <X size={15} />
            </button>}
          </div>
          {open || nearViewport ? <iframe
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
          /> : <div className={`media-waiting ${media.orientation}`} role="status"><Clapperboard size={20}/><span>La vista previa se carga al llegar a esta pieza.</span></div>}
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
