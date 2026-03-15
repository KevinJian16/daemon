const SCENE_COLORS = {
  copilot: "#6366f1",
  mentor: "#f59e0b",
  coach: "#10b981",
  operator: "#ef4444",
};

const SCENES = [
  { id: "copilot", label: "Copilot", desc: "Work collaboration" },
  { id: "mentor", label: "Mentor", desc: "Learning & growth" },
  { id: "coach", label: "Coach", desc: "Life management" },
  { id: "operator", label: "Operator", desc: "System operations" },
];

export default function SceneSelector({ active, onChange }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-3 bg-surface-1">
      {SCENES.map((s) => {
        const isActive = s.id === active;
        return (
          <button
            key={s.id}
            onClick={() => onChange(s.id)}
            className={`scene-pill ${isActive ? "scene-pill-active" : "scene-pill-inactive"}`}
            style={isActive ? { backgroundColor: SCENE_COLORS[s.id] } : undefined}
            title={s.desc}
          >
            <span
              className="inline-block w-2 h-2 rounded-full mr-1.5"
              style={{ backgroundColor: isActive ? "rgba(255,255,255,0.8)" : SCENE_COLORS[s.id] }}
            />
            {s.label}
          </button>
        );
      })}
    </div>
  );
}

export { SCENES };
