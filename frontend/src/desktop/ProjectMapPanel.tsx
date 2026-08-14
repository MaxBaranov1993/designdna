import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "../components/ui/button";
import "./project-map.css";

type Snapshot = Awaited<ReturnType<NonNullable<Window["designDNA"]>["repoCanvas"]["snapshot"]>>;

export function ProjectMapPanel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const desktop = window.designDNA;

  const load = useCallback(async () => {
    if (!desktop) return;
    setBusy(true);
    setError("");
    try {
      setSnapshot(await desktop.repoCanvas.snapshot());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }, [desktop]);

  useEffect(() => { void load(); }, [load]);

  const entitiesByArea = useMemo(() => {
    const groups = new Map<string, NonNullable<Snapshot>["entities"]>();
    for (const entity of snapshot?.entities || []) {
      const group = groups.get(entity.areaId || "unassigned") || [];
      group.push(entity);
      groups.set(entity.areaId || "unassigned", group);
    }
    return groups;
  }, [snapshot]);

  const refreshArchitecture = async () => {
    if (!desktop || !window.confirm("Перестроить семантическую карту проекта через Codex?")) return;
    setBusy(true);
    setError("");
    try {
      await desktop.repoCanvas.refresh({ effort: "medium" });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  };

  if (!desktop) {
    return <div className="project-map-empty">Project Map доступен в desktop-приложении DesignDNA.</div>;
  }

  return (
    <section className="project-map-shell">
      <header className="project-map-header">
        <div>
          <span className="project-map-eyebrow">Live semantic workspace</span>
          <h1>Project Map</h1>
          <p>Архитектура репозитория и активная работа агентов в одном локальном runtime.</p>
        </div>
        <div className="project-map-actions">
          <Button variant="outline" onClick={() => void load()} disabled={busy}>Обновить</Button>
          <Button onClick={() => void refreshArchitecture()} disabled={busy}>Architect refresh</Button>
        </div>
      </header>

      {error ? <div className="project-map-error">{error}</div> : null}
      <div className="project-map-stats">
        <Metric label="Areas" value={snapshot?.summary.areaCount ?? 0} />
        <Metric label="Entities" value={snapshot?.summary.entityCount ?? 0} />
        <Metric label="Active work" value={snapshot?.summary.activeWork ?? 0} />
        <Metric label="Revision" value={snapshot?.revision ?? 0} />
      </div>

      <div className="project-map-grid">
        {(snapshot?.areas || []).map((area) => (
          <article className="project-area" key={area.id}>
            <div className="project-area-title"><h2>{area.title || area.id}</h2><span>{entitiesByArea.get(area.id)?.length || 0}</span></div>
            {area.note ? <p>{area.note}</p> : null}
            <div className="project-entities">
              {(entitiesByArea.get(area.id) || []).map((entity) => (
                <div className="project-entity" key={entity.id}>
                  <div><strong>{entity.label || entity.id}</strong>{entity.status ? <small>{entity.status}</small> : null}</div>
                  {entity.purpose ? <p>{entity.purpose}</p> : null}
                  {entity.path ? <code>{entity.path}</code> : null}
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>

      {snapshot?.work?.length ? (
        <section className="project-work">
          <h2>Agent work</h2>
          <div>{snapshot.work.map((item) => <span key={item.id}>{item.title || item.task || item.id} · {item.status || "unknown"}</span>)}</div>
        </section>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="project-map-metric"><strong>{value}</strong><span>{label}</span></div>;
}
