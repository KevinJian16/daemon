import { useState, useEffect } from "react";
import { getStatus } from "../lib/api";

function StatusDot({ status, error }) {
  const color = error ? "#EB5757" : status ? "#4CB782" : "#E5A218";
  return (
    <span
      className="w-2 h-2 rounded-full shrink-0"
      style={{ backgroundColor: color }}
    />
  );
}

export default function Sidebar({ scenes, active, onSceneChange, showPanel, onTogglePanel }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const data = await getStatus();
        if (mounted) { setStatus(data); setError(false); }
      } catch {
        if (mounted) setError(true);
      }
    };
    check();
    const interval = setInterval(check, 15000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  return (
    <div
      className="w-[200px] flex-shrink-0 flex flex-col border-r select-none"
      style={{ background: "var(--bg-sidebar)", borderColor: "var(--border)" }}
    >
      {/* Logo */}
      <div className="px-4 h-12 flex items-center">
        <span
          className="text-[15px] font-semibold tracking-tight"
          style={{ color: "var(--text-primary)" }}
        >
          daemon
        </span>
      </div>

      {/* Scenes section */}
      <div className="px-2.5 mt-1">
        <div
          className="px-2 mb-1.5 text-2xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-muted)" }}
        >
          Scenes
        </div>
        <div className="space-y-0.5">
          {scenes.map((s) => {
            const isActive = s.id === active;
            return (
              <button
                key={s.id}
                onClick={() => onSceneChange(s.id)}
                className={`sidebar-item w-full ${isActive ? "sidebar-item-active" : ""}`}
              >
                <span
                  className="w-3 h-3 rounded-sm shrink-0"
                  style={{
                    backgroundColor: s.color,
                    opacity: isActive ? 1 : 0.55,
                  }}
                />
                <span className="truncate">{s.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom controls */}
      <div className="px-2.5 mb-2 space-y-0.5">
        <button
          onClick={onTogglePanel}
          className="sidebar-item w-full"
          style={showPanel ? { color: "var(--accent)" } : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="1" y="2" width="14" height="12" rx="2" />
            <line x1="10.5" y1="2" x2="10.5" y2="14" />
          </svg>
          <span className="truncate">Panel</span>
        </button>
      </div>

      {/* Status */}
      <div
        className="px-4 py-2.5 border-t flex items-center gap-2 text-2xs"
        style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
      >
        <StatusDot status={status} error={error} />
        <span>{error ? "Disconnected" : status ? "Connected" : "Connecting..."}</span>
      </div>
    </div>
  );
}
