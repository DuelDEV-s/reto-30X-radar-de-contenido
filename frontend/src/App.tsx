import { lazy, Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Radar,
  LayoutDashboard,
  Fingerprint,
  Plug,
  ArrowUpRight,
  ArrowRight,
  Plus,
  X,
  Search,
  TrendingUp,
  CircleHelp,
  ChevronRight,
  Check,
  Download,
  LoaderCircle,
  Radio,
  Layers,
  ScanLine,
} from "lucide-react";
import { api } from "./types";
import { personaNeedText } from "./identityText";
import type {
  Brand,
  Batch,
  Report,
  Topic,
  Identity,
  Point,
  Connector,
  SocialProfile,
  BrandContext,
  Persona,
} from "./types";
import ProfileAnalysisPanel from "./ProfileAnalysisPanel";
import RelatedAccountsPanel from "./RelatedAccountsPanel";
import DiscoveryWorkspace from "./DiscoveryWorkspace";
import SourcesWorkspace from "./SourcesWorkspace";
const EditorialWorkspace = lazy(() => import("./EditorialWorkspace"));

const compact = (n: number) =>
  new Intl.NumberFormat("es", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
const platforms: Record<string, string> = {
  linkedin: "LinkedIn",
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
};
const sameDaySeries = (points: Point[]) =>
  new Set(points.map((p) => new Date(p.observed_at).toDateString())).size <
  points.length;
const titleCase = (v: string) =>
  (v.charAt(0).toUpperCase() + v.slice(1)).replace(/\bia\b/gi, "IA");

function Sparkline({
  points,
  large = false,
}: {
  points: Point[];
  large?: boolean;
}) {
  const width = large ? 650 : 130,
    height = large ? 180 : 44,
    pad = 10;
  const values = points.map((p) => p.views),
    min = Math.min(...values),
    max = Math.max(...values);
  const times = points.map((p) => new Date(p.observed_at).getTime()),
    first = times[0],
    span = Math.max(times[times.length - 1] - first, 1);
  const coords = points
    .map(
      (p, i) =>
        `${pad + ((times[i] - first) / span) * (width - pad * 2)},${height - pad - ((p.views - min) / Math.max(max - min, 1)) * (height - pad * 2)}`,
    )
    .join(" ");
  return (
    <svg
      className={large ? "chart" : "sparkline"}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Vistas acumuladas: ${values.join(", ")}`}
    >
      <polyline
        points={coords}
        fill="none"
        stroke="currentColor"
        strokeWidth={large ? 3 : 2}
        strokeLinejoin="round"
      />
      {large &&
        points.map((p, i) => (
          <circle
            key={p.observed_at}
            cx={pad + ((times[i] - first) / span) * (width - pad * 2)}
            cy={
              height -
              pad -
              ((p.views - min) / Math.max(max - min, 1)) * (height - pad * 2)
            }
            r="4"
            fill="currentColor"
          />
        ))}
    </svg>
  );
}

export default function App() {
  const [editorialSource, setEditorialSource] = useState("");
  const [tab, setTab] = useState(() => {
      const view = new URLSearchParams(location.search).get("view") || "radar";
      return [
        "radar",
        "identity",
        "discovery",
        "integration",
        "classic",
      ].includes(view)
        ? view
        : "radar";
    }),
    [brands, setBrands] = useState<Brand[]>([]),
    [brand, setBrand] = useState<Brand | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]),
    [batchId, setBatchId] = useState(""),
    [report, setReport] = useState<Report | null>(null);
  const [batchBrandId, setBatchBrandId] = useState("");
  const [platform, setPlatform] = useState(""),
    [search, setSearch] = useState(""),
    [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false),
    [selected, setSelected] = useState<Topic | null>(null);

  useEffect(() => {
    const u = new URL(location.href);
    u.searchParams.set("view", tab);
    if (brand) u.searchParams.set("brand", brand.id);
    history.replaceState(null, "", u);
  }, [tab, brand?.id]);

  useEffect(() => {
    if (!showCreate && !selected) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const selector =
      "button:not(:disabled), a[href], input, textarea, select, summary";
    const focusable = () =>
      Array.from(dialog?.querySelectorAll<HTMLElement>(selector) || []).filter(
        (el) => el.getClientRects().length > 0,
      );
    focusable()[0]?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        setShowCreate(false);
        setSelected(null);
      }
      if (e.key === "Tab") {
        const items = focusable(),
          first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [showCreate, selected, busy]);

  useEffect(() => {
    let active = true;
    api<Brand[]>("/brands")
      .then((data) => {
        if (active) {
          setBrands(data);
          const saved = new URLSearchParams(location.search).get("brand");
          if (saved) setBrand(data.find((b) => b.id === saved) || null);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setBatches([]);
    setBatchId("");
    setBatchBrandId("");
    setReport(null);
    setSelected(null);
    if (brand)
      api<Batch[]>(`/brands/${brand.id}/trend-batches`)
        .then((data) => {
          if (active) {
            setBatches(data);
            setBatchBrandId(brand.id);
            setBatchId(
              data.find((b) => b.mode === "public")?.id || data[0]?.id || "",
            );
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [brand?.id]);
  useEffect(() => {
    if (!brand || !batchId || batchBrandId !== brand.id) {
      setReport(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setReport(null);
    const params = new URLSearchParams({
      batch_id: batchId,
      window_days: String(days),
    });
    if (platform) params.set("platform", platform);
    api<Report>(`/brands/${brand.id}/report?${params}`, {
      signal: controller.signal,
    })
      .then((data) => {
        setReport(data);
        setSelected(null);
        setError("");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [brand?.id, batchId, batchBrandId, platform, days, brand?.identity]);

  useEffect(() => {
    if (!brand || brand.profile_analysis?.status !== "pending" || busy) return;
    const id = brand.id;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await api<Brand>(`/brands/${id}/profiles/analyze`, {
          method: "POST",
          body: "{}",
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setBrand((current) => (current?.id === id ? data : current));
        setBrands((items) =>
          items.map((item) => (item.id === id ? data : item)),
        );
        if (data.profile_analysis?.status === "pending")
          timer = setTimeout(poll, 4000);
        else
          setNotice(
            "Recolección terminada. Revisa las fuentes y la propuesta de identidad.",
          );
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(
            e instanceof Error
              ? e.message
              : "No se pudo consultar la recolección.",
          );
          timer = setTimeout(poll, 15000);
        }
      }
    };
    timer = setTimeout(poll, 4000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [brand?.id, brand?.profile_analysis?.status, busy]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No se pudo completar la acción",
      );
    } finally {
      setBusy(false);
    }
  }
  async function loadDemo() {
    await run(async () => {
      const data = await api<{ brand: Brand; batch_id: string }>("/demo", {
        method: "POST",
      });
      setBrands((b) => [data.brand, ...b]);
      setBrand(data.brand);
      setTab("radar");
    });
  }
  async function created(body: unknown) {
    await run(async () => {
      const data = await api<Brand>("/brands", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setBrands((b) => [data, ...b]);
      setBrand(data);
      setTab("identity");
      setShowCreate(false);
      setNotice("Marca creada. Revisa la identidad antes de confirmarla.");
    });
  }
  async function saveIdentity(identity: Identity) {
    await run(async () => {
      const data = await api<Brand>(`/brands/${brand!.id}/identity`, {
        method: "PUT",
        body: JSON.stringify(identity),
      });
      setBrand(data);
      setBrands((b) => b.map((x) => (x.id === data.id ? data : x)));
      setNotice("Identidad guardada.");
    });
  }
  async function analyzeProfiles(
    profiles: SocialProfile[],
    apply: boolean,
    force: boolean,
    refreshBrightData?: boolean,
  ) {
    await run(async () => {
      const data = await api<Brand>(`/brands/${brand!.id}/profiles/analyze`, {
        method: "POST",
        body: JSON.stringify({
          profiles,
          brand_accounts_confirmed: true,
          apply_to_identity: apply,
          force,
          refresh_bright_data: refreshBrightData ?? false,
        }),
      });
      setBrand(data);
      setBrands((items) => items.map((b) => (b.id === data.id ? data : b)));
      setNotice(
        data.profile_analysis?.status === "pending"
          ? "Recolección iniciada. Los resultados se actualizarán automáticamente."
          : apply
            ? "Propuesta aplicada como borrador. Revísala y confirma la identidad."
            : "Consulta terminada. Revisa los datos y el estado de cada fuente.",
      );
    });
  }
  async function interpretProfiles(apply: boolean) {
    await run(async () => {
      const data = await api<Brand>(`/brands/${brand!.id}/profiles/interpret`, {
        method: "POST",
        body: JSON.stringify({ apply_to_identity: apply }),
      });
      setBrand(data);
      setBrands((items) =>
        items.map((item) => (item.id === data.id ? data : item)),
      );
      setNotice(
        apply
          ? "Propuesta aplicada como borrador. Revísala antes de confirmar."
          : "Interpretación actualizada con los datos guardados. Revisa la propuesta; tu identidad se conserva.",
      );
    });
  }
  async function saveBrandContext(context: BrandContext) {
    await run(async () => {
      const data = await api<Brand>(`/brands/${brand!.id}/context`, {
        method: "PUT", body: JSON.stringify(context),
      });
      setBrand(data);
      setBrands(items => items.map(item => item.id === data.id ? data : item));
      setNotice("Contexto guardado y personas propuestas actualizadas. Revisa la evidencia antes de aplicar el borrador.");
    });
  }
  async function importBatch(raw: string) {
    await run(async () => {
      const data = await api<{ id: string }>(
        `/brands/${brand!.id}/trend-batches`,
        { method: "POST", body: JSON.stringify(JSON.parse(raw)) },
      );
      const list = await api<Batch[]>(`/brands/${brand!.id}/trend-batches`);
      setBatches(list);
      setBatchId(data.id);
      openEditorial(`batch:${data.id}`);
      setNotice("Lote importado y validado. El radar ya puede analizarlo.");
    });
  }
  async function openBatch(id: string) {
    await run(async () => {
      const list = await api<Batch[]>(`/brands/${brand!.id}/trend-batches`);
      setBatches(list);
      setBatchBrandId(brand!.id);
      setBatchId(id);
      setTab("classic");
      setNotice("Lote del radar LinkedIn + YouTube cargado en el paso 3.");
    });
  }
  function openEditorial(source: string) {
    const u = new URL(location.href);
    u.searchParams.set("radar_source", source);
    if (brand) u.searchParams.set("brand", brand.id);
    for (const key of ["radar_topic", "radar_search", "radar_network"])
      u.searchParams.delete(key);
    history.replaceState(null, "", u);
    setEditorialSource(source);
    setTab("radar");
  }
  const topics =
    report?.topics.filter((t) =>
      t.topic.toLowerCase().includes(search.toLowerCase()),
    ) || [];
  const currentBatch = batches.find((b) => b.id === batchId);
  const nav = [
    {
      id: "radar",
      label: "Radar de contenido",
      icon: LayoutDashboard,
      step: "03",
    },
    {
      id: "identity",
      label: "Identidad de marca",
      icon: Fingerprint,
      step: "01",
    },
    {
      id: "discovery",
      label: "Descubrimiento",
      icon: Search,
      step: "02",
    },
    {
      id: "integration",
      label: "Fuentes e integración",
      icon: Plug,
      step: "02",
    },
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="wordmark"
          href="#"
          aria-label="30X inicio"
          onClick={() => setTab("radar")}
        >
          30<span>X</span>
          <i /> <small>RADAR</small>
        </a>
        <div className="workspace-label">TU ESPACIO DE TRABAJO</div>
        <label className="brand-select">
          <span className="brand-avatar">
            {brand ? brand.brief.name.slice(0, 1) : "+"}
          </span>
          <select
            aria-label="Seleccionar marca"
            value={brand?.id || ""}
            onChange={(e) => {
              setError("");
              setNotice("");
              setBrand(brands.find((b) => b.id === e.target.value) || null);
            }}
          >
            <option value="">Selecciona una marca</option>
            {brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.brief.name}
              </option>
            ))}
          </select>
        </label>
        <nav>
          {nav.map(({ id, label, icon: Icon, step }) => (
            <button
              key={id}
              className={tab === id ? "nav-item active" : "nav-item"}
              onClick={() => {
                setTab(id);
                setNotice("");
              }}
            >
              <Icon size={19} />
              {label}
              <small>{step}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <Radio size={21} />
          <strong>De señal a oportunidad.</strong>
          <p>Entiende qué se mueve y decide qué vale la pena crear.</p>
          <div>
            <span className="status-dot" /> Solo fuentes públicas
          </div>
        </div>
        <div className="sidebar-bottom">
          <span className="team-avatar">30</span>
          <div>
            Equipo de contenido<small>Hackathon · 30X</small>
          </div>
          <Layers size={17} />
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            Workspace <ChevronRight size={14} />{" "}
            <strong className="desktop-brand">
              {brand?.brief.name || "Tu próxima señal"}
            </strong>
            <select
              className="compact-brand"
              aria-label="Cambiar marca"
              value={brand?.id || ""}
              onChange={(e) => {
                setError("");
                setNotice("");
                setBrand(brands.find((b) => b.id === e.target.value) || null);
              }}
            >
              <option value="">Seleccionar marca</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.brief.name}
                </option>
              ))}
            </select>
          </div>
          <span className="prototype">
            PROTOTIPO <span>v0.1</span>
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                <span /> INTELIGENCIA DE CONTENIDO
              </div>
              <h1>
                {tab === "radar"
                  ? "Encuentra tu próxima gran idea."
                  : tab === "identity"
                    ? "Primero, entiende tu marca."
                    : tab === "discovery"
                      ? "Descubre qué se mueve en tu tema."
                      : tab === "integration"
                        ? "Tus fuentes, conectadas."
                        : "Explora el historial de tus lotes."}
              </h1>
              <p>
                {tab === "radar"
                  ? "Menos ruido. Más contexto para crear contenido que conecte."
                  : tab === "identity"
                    ? "Una identidad clara convierte tendencias en oportunidades relevantes."
                    : tab === "discovery"
                      ? "Elige Instagram, TikTok, LinkedIn o YouTube y explora la evidencia antes de crear."
                      : tab === "integration"
                        ? "Corridas guardadas, estado de conectores y acceso a tus informes."
                        : "Observaciones y análisis del contrato de lotes v1."}
              </p>
            </div>
            <button className="button dark" onClick={() => setShowCreate(true)}>
              <Plus size={17} /> Nueva marca
            </button>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button aria-label="Cerrar error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <Check size={16} />
              {notice}
            </div>
          )}
          {tab === "classic" && currentBatch?.mode === "demo" && (
            <div className="demo-banner">
              <ScanLine size={17} />
              <strong>Estás explorando una demo.</strong>
              <span>
                Las piezas, cifras y enlaces son ficticios. No son tendencias
                observadas.
              </span>
            </div>
          )}
          {!brand ? (
            <section className="welcome">
              <div>
                <span className="pill green">EL CONTEXTO CAMBIA TODO</span>
                <h2>
                  No persigas lo viral.
                  <br />
                  Encuentra lo relevante.
                </h2>
                <p>
                  Conecta la identidad de tu marca con señales de contenido.
                  Descubre qué está acelerando en tu muestra, qué podría
                  explicar su resultado y cómo adaptarlo.
                </p>
                <div className="welcome-actions">
                  <button
                    className="button dark"
                    onClick={() => setShowCreate(true)}
                  >
                    Crear mi primera marca <ArrowRight size={17} />
                  </button>
                  <button className="button" disabled={busy} onClick={loadDemo}>
                    {busy ? (
                      <LoaderCircle className="spin" size={17} />
                    ) : (
                      <Radar size={17} />
                    )}{" "}
                    Explorar demo
                  </button>
                </div>
                <small>
                  Demo sin claves de API · Fuentes públicas · Evidencia visible
                </small>
              </div>
              <div className="radar-art" aria-hidden="true">
                <div className="orbit one" />
                <div className="orbit two" />
                <div className="orbit three" />
                <div className="radar-cross" />
                <span className="radar-core">
                  <Radar size={38} />
                </span>
                <span className="signal s1" />
                <span className="signal s2" />
                <span className="signal s3" />
                <div className="signal-label">↗ Una señal con contexto</div>
              </div>
            </section>
          ) : tab === "identity" ? (
            <IdentityEditor
              key={brand.id + JSON.stringify(brand.identity)}
              brand={brand}
              onSave={saveIdentity}
              onAnalyze={analyzeProfiles}
              onInterpret={interpretProfiles}
              onContextSave={saveBrandContext}
              busy={busy}
            />
          ) : tab === "discovery" ? (
            <DiscoveryWorkspace
              brand={brand}
              onOpenBatch={openBatch}
              onOpenEditorial={openEditorial}
            />
          ) : tab === "radar" ? (
            <Suspense
              fallback={
                <div className="ed-loading" role="status">
                  <LoaderCircle className="spin" /> Preparando informe
                  editorial…
                </div>
              }
            >
              <EditorialWorkspace
                key={brand.id}
                brand={brand}
                requestedSource={editorialSource}
                onDiscover={() => setTab("discovery")}
                onClassic={() => setTab("classic")}
              />
            </Suspense>
          ) : tab === "integration" ? (
            <SourcesWorkspace
              key={brand.id}
              brand={brand}
              onDiscover={() => setTab("discovery")}
              onOpenEditorial={openEditorial}
            >
              <Integration
                brand={brand}
                batches={batches}
                busy={busy}
                onImport={importBatch}
              />
            </SourcesWorkspace>
          ) : (
            <>
              <section className="radar-intro">
                <div>
                  <span className="pill green">
                    <Radio size={13} /> RADAR DE OPORTUNIDADES
                  </span>
                  <h2>La señal está en el contexto.</h2>
                  <p>
                    Prioriza por aceleración, afinidad de marca y evidencia
                    disponible.
                  </p>
                </div>
                <div className="intro-symbol">
                  <Radar size={92} strokeWidth={0.8} />
                </div>
              </section>
              <div className="stats">
                <Stat
                  label="Tópicos en la muestra"
                  value={String(report?.total_topics ?? "—")}
                  icon={<Layers size={18} />}
                  note="Según los filtros activos"
                />
                <Stat
                  label="Piezas del lote"
                  value={String(currentBatch?.posts ?? 0)}
                  icon={<ScanLine size={18} />}
                  note="La muestra no representa toda la red"
                />
                <Stat
                  label="En aceleración"
                  value={String(
                    report?.topics.filter((t) => t.stage === "En aceleración")
                      .length ?? "—",
                  )}
                  icon={<TrendingUp size={18} />}
                  note="Cambio de velocidad de vistas ≥ 25%"
                />
                <Stat
                  label="Identidad de marca"
                  value={
                    brand.identity.status === "confirmed"
                      ? "Confirmada"
                      : "Por revisar"
                  }
                  icon={<Fingerprint size={18} />}
                  note={
                    brand.identity.status === "confirmed"
                      ? "Revisada por el equipo"
                      : "Borrador a partir de tu brief"
                  }
                />
              </div>
              <section className="opportunities">
                <div className="section-title">
                  <div>
                    <h2>
                      En tu radar <span>{topics.length}</span>
                    </h2>
                    <p>Señales para explorar, con sus límites a la vista.</p>
                  </div>
                  <button
                    className="button small"
                    disabled={!report}
                    onClick={() => {
                      const blob = new Blob([JSON.stringify(report, null, 2)], {
                        type: "application/json",
                      });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = "radar-report.json";
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    <Download size={15} /> Exportar JSON
                  </button>
                </div>
                <div className="filters">
                  <label className="search">
                    <Search size={17} />
                    <input
                      placeholder="Buscar un tópico…"
                      aria-label="Buscar tópico"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </label>
                  <select
                    aria-label="Filtrar red social"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                  >
                    <option value="">Todas las redes</option>
                    {Object.entries(platforms).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Ventana temporal"
                    value={days}
                    onChange={(e) => setDays(Number(e.target.value))}
                  >
                    <option value={7}>Últimos 7 días</option>
                    <option value={14}>Últimos 14 días</option>
                    <option value={30}>Últimos 30 días</option>
                  </select>
                  <select
                    aria-label="Seleccionar lote"
                    value={batchId}
                    onChange={(e) => setBatchId(e.target.value)}
                  >
                    <option value="">Selecciona un lote</option>
                    {batches.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.mode === "demo" ? "Demo" : "Público"} ·{" "}
                        {b.source.slice(0, 35)} ·{" "}
                        {new Date(b.created_at).toLocaleDateString("es")}
                      </option>
                    ))}
                  </select>
                </div>
                {loading ? (
                  <div className="empty" role="status">
                    <LoaderCircle className="spin" /> Analizando señales…
                  </div>
                ) : !topics.length ? (
                  <div className="empty">
                    <Radar size={32} />
                    <h3>
                      {batches.length
                        ? "No hay señales con estos filtros"
                        : "Tu radar está listo para recibir señales"}
                    </h3>
                    <p>
                      {batches.length
                        ? "Prueba otra red, ventana o término de búsqueda."
                        : "Importa el JSON del paso 2 para empezar a comparar oportunidades."}
                    </p>
                    {!batches.length && (
                      <button
                        className="button dark"
                        onClick={() => setTab("integration")}
                      >
                        Conectar datos <ArrowRight size={16} />
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="topic-list">
                    <div className="list-head">
                      <span>TÓPICO / SEÑAL</span>
                      <span>ACELERACIÓN</span>
                      <span>AFINIDAD</span>
                      <span>PRIORIDAD</span>
                      <span />
                    </div>
                    {topics.map((t, i) => (
                      <button
                        key={t.topic}
                        className="topic-row"
                        onClick={() => setSelected(t)}
                      >
                        <div className="topic-name">
                          <span className={"topic-icon tone-" + (i % 3)}>
                            {i % 3 === 0 ? (
                              <Radio size={21} />
                            ) : i % 3 === 1 ? (
                              <Layers size={21} />
                            ) : (
                              <TrendingUp size={21} />
                            )}
                          </span>
                          <div>
                            <h3>{titleCase(t.topic)}</h3>
                            <p>
                              <span
                                className={
                                  t.stage === "En aceleración"
                                    ? "dot green-dot"
                                    : "dot"
                                }
                              />
                              {t.stage}
                              <span className="middot">·</span>
                              {t.sample_size} piezas
                            </p>
                          </div>
                        </div>
                        <div className="momentum">
                          <strong>
                            {t.acceleration_pct === null
                              ? "Sin serie"
                              : `${t.acceleration_pct > 0 ? "+" : ""}${t.acceleration_pct}%`}
                          </strong>
                          <Sparkline points={t.top_content.snapshots} />
                        </div>
                        <div className="fit">
                          <strong>{t.relevance}%</strong>
                          <span>
                            <i style={{ width: `${t.relevance}%` }} />
                          </span>
                        </div>
                        <div className="priority">
                          <strong>
                            {t.score}
                            <small>/100</small>
                          </strong>
                          <span>Confianza {t.confidence}</span>
                        </div>
                        <ArrowUpRight size={19} />
                      </button>
                    ))}
                  </div>
                )}
              </section>
              <div className="method-note">
                <CircleHelp size={17} />
                <p>
                  Una señal no es una certeza. Las explicaciones son hipótesis;
                  la afinidad se calcula por coincidencia de tópicos.{" "}
                  <button onClick={() => setTab("integration")}>
                    Ver metodología <ArrowUpRight size={13} />
                  </button>
                </p>
              </div>
            </>
          )}
          <footer>
            <span>
              30X RADAR <span> / </span> De la intuición a la evidencia.
            </span>
            <span>Hecho para equipos que crean.</span>
          </footer>
        </div>
      </main>
      {showCreate && (
        <div
          className="modal-backdrop"
          onClick={() => !busy && setShowCreate(false)}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label="Cerrar"
              disabled={busy}
              onClick={() => setShowCreate(false)}
            >
              <X />
            </button>
            <div className="eyebrow">PASO 01</div>
            <h2 id="create-title">Dale contexto a tu radar.</h2>
            <p>
              Agrega las redes de tu marca. Consultaremos las fuentes públicas
              configuradas para preparar su identidad.
            </p>
            {error && (
              <div className="alert error" role="alert">
                {error}
              </div>
            )}
            <CreateForm busy={busy} onCreate={created} />
          </section>
        </div>
      )}
      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <section
            className="modal detail"
            role="dialog"
            aria-modal="true"
            aria-labelledby="topic-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label="Cerrar detalle"
              onClick={() => setSelected(null)}
            >
              <X />
            </button>
            <div className="eyebrow">
              OPORTUNIDAD EDITORIAL ·{" "}
              {report?.mode === "demo" ? "DEMO FICTICIA" : "MUESTRA PÚBLICA"}
            </div>
            <h2 id="topic-title">{titleCase(selected.topic)}</h2>
            <div className="detail-badges">
              <span className="pill green">{selected.stage}</span>
              <span className="pill">Confianza {selected.confidence}</span>
              <span className="pill">
                {selected.sample_size} piezas · {selected.series_count} series
                comparables
              </span>
            </div>
            <h3>¿Por qué puede ser relevante?</h3>
            <p>{selected.why_relevant}</p>
            <h3>¿Qué podría explicar el resultado?</h3>
            {selected.why_it_may_work.map((t) => (
              <p key={t}>{t}</p>
            ))}
            <div className="adaptation">
              <span className="eyebrow">TU PRÓXIMA PRUEBA</span>
              <p>{selected.adaptation}</p>
            </div>
            <h3>Vistas acumuladas de la pieza principal</h3>
            <p className="muted">
              {selected.top_content.title} ·{" "}
              {platforms[selected.top_content.platform]} ·{" "}
              {compact(selected.top_content.snapshots.at(-1)!.views)} vistas
            </p>
            <Sparkline points={selected.top_content.snapshots} large />
            <div className="chart-dates">
              {selected.top_content.snapshots.map((p) => (
                <span key={p.observed_at}>
                  {new Date(p.observed_at).toLocaleString("es", {
                    day: "numeric",
                    month: "short",
                    // Observaciones del mismo día: la hora distingue cada punto.
                    ...(sameDaySeries(selected.top_content.snapshots)
                      ? { hour: "2-digit", minute: "2-digit" }
                      : {}),
                  })}
                  <strong>{compact(p.views)}</strong>
                </span>
              ))}
            </div>
            <p className="muted">
              La curva muestra acumulados; el score compara velocidades entre
              intervalos de tiempo.
            </p>
            {report?.mode === "demo" ? (
              <p className="demo-source">
                Fuente: fixture sintético. Enlace ficticio deshabilitado.
              </p>
            ) : (
              <a
                className="button"
                href={selected.top_content.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Ver pieza pública <ArrowUpRight size={16} />
              </a>
            )}
            <p className="source-reference">
              Procedencia declarada: {selected.top_content.source_reference}
            </p>
            <details>
              <summary>Cómo se calculó y qué no sabemos</summary>
              <p>{report?.methodology}</p>
              {report?.limitations.map((l) => (
                <p key={l}>• {l}</p>
              ))}
            </details>
          </section>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  icon,
  note,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  note: string;
}) {
  return (
    <div className="stat">
      <div>
        {label}
        {icon}
      </div>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function CreateForm({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (body: unknown) => void;
}) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  useEffect(() => {
    let active = true;
    api<Connector[]>("/profile-connectors")
      .then((items) => {
        if (active) setConnectors(items);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const profiles = Object.keys(platforms)
      .filter((p) => f.get(p))
      .map((p) => ({
        platform: p,
        url: String(f.get(p)),
        description: String(f.get(`${p}_description`) || ""),
      }));
    onCreate({
      name: f.get("name"),
      description: f.get("description"),
      audience: f.get("audience"),
      region: f.get("region"),
      topics: String(f.get("topics") || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      profiles,
      brand_accounts_confirmed: f.get("confirmed") === "on",
    });
  }
  return (
    <form onSubmit={submit}>
      <label>
        Nombre de la marca
        <input
          name="name"
          placeholder="Ej. 30X"
          required
          minLength={2}
          maxLength={100}
        />
      </label>
      <div className="profile-form-intro">
        <h3>Redes sociales de la marca</h3>
        <p>
          Agrega uno o varios perfiles. La consulta se ejecuta al crear la
          marca; si falta acceso, verás qué configurar.
        </p>
      </div>
      {Object.entries(platforms).map(([p, label]) => {
        const connector = connectors.find((c) => c.platform === p);
        return (
          <label key={p}>
            {label}
            <input
              name={p}
              type="url"
              placeholder={
                p === "youtube" || p === "tiktok"
                  ? `https://www.${p}.com/@${p === "tiktok" ? "tu_marca" : "tu-marca"}`
                  : p === "linkedin"
                    ? "https://www.linkedin.com/company/tu-marca"
                    : "https://www.instagram.com/tu-marca"
              }
              maxLength={500}
            />
            <small className="connector-status">
              {connector?.configured
                ? connector.primary?.configured
                  ? p === "instagram" || p === "youtube"
                    ? "Bright Data principal · API oficial como respaldo"
                    : "Bright Data · perfiles públicos de marca"
                  : "API oficial disponible como respaldo"
                : connector?.missing.length
                  ? "Requiere credenciales de servidor"
                  : "Conector automático aún no disponible"}
            </small>
          </label>
        );
      })}
      <label className="checkbox-label">
        <input name="confirmed" type="checkbox" /> Confirmo que los enlaces
        corresponden a cuentas públicas de la marca, sin perfiles personales.
      </label>
      <details>
        <summary>Añadir contexto adicional (opcional)</summary>
        <label>
          ¿Qué hace y qué aporta?
          <textarea
            name="description"
            placeholder="Describe su propuesta y el contenido que produce…"
            maxLength={5000}
          />
        </label>
        <div className="form-grid">
          <label>
            Audiencia
            <input
              name="audience"
              placeholder="Líderes y equipos que aprenden IA"
              maxLength={1000}
            />
          </label>
          <label>
            Región
            <input
              name="region"
              defaultValue="Latinoamérica"
              required
              minLength={2}
              maxLength={100}
            />
          </label>
        </div>
        <label>
          Tópicos separados por comas
          <input
            name="topics"
            placeholder="agentes de IA, automatización, negocios"
            maxLength={1500}
          />
        </label>
        <details>
          <summary>Aportar descripciones públicas manualmente</summary>
          {Object.entries(platforms).map(([p, label]) => (
            <div className="profile-fields" key={p}>
              <label>{label}</label>
              <label>
                Descripción pública de {label}
                <textarea
                  name={`${p}_description`}
                  placeholder="Texto de la marca, sin datos personales"
                  maxLength={3000}
                />
              </label>
            </div>
          ))}
        </details>
      </details>
      <p className="muted">
        Nombre + perfiles es suficiente para empezar. Las credenciales se
        configuran en el servidor. La propuesta usa textos disponibles y reglas;
        no inventa vistas ni audiencia.
      </p>
      <button className="button dark full" disabled={busy}>
        {busy ? (
          <LoaderCircle size={17} className="spin" />
        ) : (
          <Fingerprint size={17} />
        )}{" "}
        {busy ? "Consultando perfiles…" : "Analizar redes y crear marca"}
      </button>
    </form>
  );
}

function IdentityEditor({
  brand,
  onSave,
  onAnalyze,
  onInterpret,
  onContextSave,
  busy,
}: {
  brand: Brand;
  onSave: (value: Identity) => void;
  onInterpret: (apply: boolean) => void;
  onContextSave: (context: BrandContext) => void;
  onAnalyze: (
    profiles: SocialProfile[],
    apply: boolean,
    force: boolean,
    refreshBrightData?: boolean,
  ) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(() => ({
    ...brand.identity,
    personas: brand.identity.personas.map(p => ({...p, need: personaNeedText(p.need)})),
  }));
  const edit = (key: keyof Identity, v: unknown) =>
    setValue((x) => ({ ...x, [key]: v }));
  const editPersona = (i: number, key: keyof Persona, text: string | string[]) =>
    edit("personas", value.personas.map((p, j) => i === j ? { ...p, [key]: text, basis: "team" } : p));
  return (
    <>
      <ProfileAnalysisPanel
        key={brand.id + JSON.stringify(brand.brief.profiles)}
        brand={brand}
        busy={busy}
        onAnalyze={onAnalyze}
        onInterpret={onInterpret}
        onContextSave={onContextSave}
      />
      <RelatedAccountsPanel brand={brand} />
      <section className="identity-layout">
        <div className="panel">
          <div className="eyebrow">PASO 01 · IDENTIDAD DE MARCA</div>
          <h2>{brand.brief.name}</h2>
          <p className="muted">
            {value.status === "draft"
              ? "Borrador para revisar con tu equipo."
              : "Identidad confirmada por tu equipo."}{" "}
            Las personas son segmentos de audiencia, sin datos personales.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onSave({ ...value, status: "confirmed", method: "human_review" });
            }}
          >
            <label>
              Definición general
              <textarea
                rows={4}
                value={value.summary}
                onChange={(e) => edit("summary", e.target.value)}
                required
                minLength={10}
                maxLength={5000}
              />
            </label>
            <div className="form-grid">
              <label>
                Audiencia
                <input
                  value={value.audience}
                  onChange={(e) => edit("audience", e.target.value)}
                  required
                  minLength={5}
                  maxLength={1000}
                />
              </label>
              <label>
                Región
                <input
                  value={value.region}
                  onChange={(e) => edit("region", e.target.value)}
                  required
                  minLength={2}
                  maxLength={100}
                />
              </label>
            </div>
            <label>
              Tópicos de la marca (separados por comas)
              <input
                value={value.topics.join(",")}
                onChange={(e) => edit("topics", e.target.value.split(","))}
                required
              />
            </label>
            <h3>User personas de la identidad</h3>
            <p className="muted">Las tarjetas de arriba son propuestas. «Usar propuesta como borrador» incorpora sus detalles aquí para editarlos y confirmarlos.</p>
            {value.personas.map((p, i) => (
              <div className="persona-edit" key={i}>
                <label>
                  Rol / segmento
                  <input
                    value={p.role}
                    onChange={(e) => editPersona(i, "role", e.target.value)}
                    required
                    minLength={2}
                    maxLength={120}
                  />
                </label>
                <label>
                  Necesidad
                  <textarea
                    value={p.need}
                    onChange={(e) => editPersona(i, "need", e.target.value)}
                    required
                    minLength={5}
                    maxLength={500}
                  />
                </label>
                <details className="persona-editor-details">
                  <summary>Objetivo, barreras e ideas de contenido</summary>
                  <label>Objetivo del segmento<textarea maxLength={500} value={p.goal || ""} onChange={e => editPersona(i, "goal", e.target.value)} /></label>
                  <label>Barreras por validar (una por línea)<textarea value={(p.barriers || []).join("\n")} onChange={e => editPersona(i, "barriers", e.target.value.split("\n").slice(0, 5))} /></label>
                  <label>Ideas de contenido (una por línea)<textarea value={(p.content_angles || []).join("\n")} onChange={e => editPersona(i, "content_angles", e.target.value.split("\n").slice(0, 5))} /></label>
                  <label>Pregunta para validar<textarea maxLength={500} value={p.validation_question || ""} onChange={e => editPersona(i, "validation_question", e.target.value)} /></label>
                </details>
                {value.personas.length > 1 && (
                  <button
                    className="text-button"
                    type="button"
                    onClick={() =>
                      edit(
                        "personas",
                        value.personas.filter((_, j) => j !== i),
                      )
                    }
                  >
                    Quitar segmento
                  </button>
                )}
              </div>
            ))}
            <div className="form-actions">
              <button
                type="button"
                className="button"
                disabled={value.personas.length >= 6}
                onClick={() =>
                  edit("personas", [...value.personas, { role: "", need: "" }])
                }
              >
                <Plus size={16} /> Añadir persona
              </button>
              <button className="button dark" disabled={busy}>
                <Check size={17} /> Guardar y confirmar
              </button>
            </div>
          </form>
        </div>
        <aside className="panel context-panel">
          <Fingerprint size={34} />
          <h3>Tu filtro de relevancia</h3>
          <p>
            Los tópicos de esta identidad alimentan el score de afinidad. Las
            recomendaciones incorporan tu audiencia y región.
          </p>
          <div className="tags">
            {value.topics.filter(Boolean).map((t, i) => (
              <span key={i}>{t}</span>
            ))}
          </div>
          <h3>Referencias de la marca</h3>
          {brand.brief.profiles.length ? (
            brand.brief.profiles.map((p) => (
              <div key={p.url}>
                <a href={p.url} target="_blank" rel="noopener noreferrer">
                  {platforms[p.platform]} <ArrowUpRight size={13} />
                </a>
                <p>{p.description || "Sin descripción aportada."}</p>
              </div>
            ))
          ) : (
            <p>Sin perfiles. Puedes trabajar directamente con el brief.</p>
          )}
          <small>
            Método de identidad: {brand.identity.method}. El análisis de
            perfiles muestra qué fuentes se consultaron y qué datos están
            disponibles. Una identidad confirmada se conserva hasta que apliques
            otra propuesta.
          </small>
        </aside>
      </section>
    </>
  );
}

function Integration({
  brand,
  batches,
  busy,
  onImport,
}: {
  brand: Brand;
  batches: Batch[];
  busy: boolean;
  onImport: (raw: string) => void;
}) {
  const [raw, setRaw] = useState(""),
    [parseError, setParseError] = useState("");
  return (
    <div className="integration-layout">
      <section className="panel">
        <div className="eyebrow">PASO 02 → PASO 03</div>
        <h2>Importa observaciones de otro recolector.</h2>
        <p>
          Usa esta opción para integrar un lote externo con evidencia temporal.
          Las corridas del paso 2 ya aparecen automáticamente en Fuentes
          guardadas.
        </p>
        <div className="endpoint">
          <span>POST</span>
          <code>/api/brands/{brand.id}/trend-batches</code>
        </div>
        <label>
          Importar archivo JSON
          <input
            type="file"
            accept=".json,application/json"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) {
                if (file.size > 2_000_000) {
                  setParseError("Máximo 2 MB por archivo.");
                  return;
                }
                setRaw(await file.text());
                setParseError("");
              }
            }}
          />
        </label>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            try {
              JSON.parse(raw);
              setParseError("");
              onImport(raw);
            } catch {
              setParseError("El texto no es JSON válido.");
            }
          }}
        >
          <label>
            Lote JSON
            <textarea
              className="code-editor"
              rows={12}
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              placeholder='{"schema_version":"1.0","mode":"public", ...}'
              required
            />
          </label>
          {parseError && (
            <p className="inline-error" role="alert">
              {parseError}
            </p>
          )}
          <p className="muted">
            El lote debe declarar origen público, uso permitido y ausencia de
            datos personales. El contrato acepta únicamente campos definidos.
          </p>
          <button className="button dark" disabled={busy}>
            <Plug size={17} /> Validar e importar lote
          </button>
        </form>
      </section>
      <aside>
        <section className="panel">
          <h3>Contrato v1.0</h3>
          <p>
            Disponible en <code>docs/step-2-contract.md</code> y en Swagger{" "}
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              /docs <ArrowUpRight size={12} />
            </a>
            .
          </p>
          <ul>
            <li>URLs públicas de la red indicada.</li>
            <li>Tópico, formato, título y gancho.</li>
            <li>Vistas acumuladas + fecha con zona horaria.</li>
            <li>3 observaciones para comparar dos velocidades.</li>
            <li>Procedencia y método de obtención.</li>
          </ul>
          <p className="muted">
            No se recolectan autores, seguidores, comentarios ni perfiles
            personales.
          </p>
        </section>
        <section className="panel">
          <h3>{batches.length} lotes disponibles</h3>
          {batches.map((b) => (
            <div className="batch-item" key={b.id}>
              <strong>
                {b.mode === "demo" ? "Demo sintética" : "Muestra pública"}
              </strong>
              <span>
                {b.posts} piezas · {b.source}
              </span>
            </div>
          ))}
          {!batches.length && <p>Aún no hay datos importados.</p>}
        </section>
        <section className="panel">
          <h3>Cómo priorizamos</h3>
          <div className="weight">
            <span>Afinidad de tópicos</span>
            <strong>45%</strong>
          </div>
          <div className="weight">
            <span>Aceleración de vistas/día</span>
            <strong>35%</strong>
          </div>
          <div className="weight">
            <span>Evidencia temporal</span>
            <strong>20%</strong>
          </div>
          <p className="muted">
            Heurística v1. No mide causalidad, saturación ni crecimiento de toda
            una plataforma.
          </p>
        </section>
      </aside>
    </div>
  );
}
