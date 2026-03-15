import { useState } from "react";
import SceneSelector from "./components/SceneSelector";
import SceneChat from "./components/SceneChat";
import PanelView from "./components/PanelView";
import StatusBar from "./components/StatusBar";

export default function App() {
  const [scene, setScene] = useState("copilot");
  const [showPanel, setShowPanel] = useState(false);

  return (
    <div className="h-screen flex flex-col">
      {/* Top: scene selector + panel toggle */}
      <div className="flex items-center justify-between bg-surface-1">
        <SceneSelector active={scene} onChange={setScene} />
        <button
          onClick={() => setShowPanel(!showPanel)}
          className="px-3 py-1.5 mr-4 text-xs text-gray-400 hover:text-gray-200 transition-colors"
          title="Toggle panel (digests & decisions)"
        >
          {showPanel ? "Hide Panel" : "Panel"}
        </button>
      </div>

      {/* Main area: chat + optional panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat takes remaining space */}
        <div className="flex-1 flex flex-col min-w-0">
          <SceneChat key={scene} scene={scene} />
        </div>

        {/* Panel sidebar */}
        {showPanel && (
          <div className="w-80 border-l border-surface-3 bg-surface-1 flex-shrink-0 overflow-hidden">
            <PanelView scene={scene} />
          </div>
        )}
      </div>

      {/* Bottom: status bar */}
      <StatusBar />
    </div>
  );
}
