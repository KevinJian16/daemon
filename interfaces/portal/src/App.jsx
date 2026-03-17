import { useState, useEffect } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarInset,
  useSidebar,
} from "@/components/ui/sidebar";
import SceneChat from "./components/SceneChat";
import PanelView from "./components/PanelView";
import AppSidebarFooter from "./components/AppSidebarFooter";

// Source: .ref/SYSTEM_DESIGN.md §0 lines 135-140
const SCENES = [
  { id: "copilot", label: "Copilot", desc: "You lead, Daemon executes", color: "var(--scene-copilot)" },
  { id: "instructor", label: "Instructor", desc: "Daemon guides, you learn", color: "var(--scene-instructor)" },
  { id: "navigator", label: "Navigator", desc: "Daemon plans, you perform", color: "var(--scene-navigator)" },
  { id: "autopilot", label: "Autopilot", desc: "Daemon acts, you oversee", color: "var(--scene-autopilot)" },
];

const SCENE_GREETINGS = {
  copilot: "What are we working on?",
  instructor: "What would you like to explore?",
  navigator: "How's it going today?",
  autopilot: "Everything's running. Anything to review?",
};

// Half-screen threshold: collapse sidebars when window is narrow (split mode)
const SPLIT_THRESHOLD = 900;

function AppInner() {
  const [scene, setScene] = useState("copilot");
  const [showPanel, setShowPanel] = useState(false);
  const { setOpen: setSidebarOpen } = useSidebar();

  // Auto-collapse both sidebars when window becomes narrow (split screen)
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < SPLIT_THRESHOLD) {
        setSidebarOpen(false);
        setShowPanel(false);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [setSidebarOpen]);

  const sceneInfo = SCENES.find((s) => s.id === scene);

  return (
    <>
      {/* Left sidebar */}
      <Sidebar>
        <SidebarHeader className="px-4 py-3">
          <span className="text-sm font-semibold tracking-tight">Daemon</span>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Scenes</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {SCENES.map((s) => (
                  <SidebarMenuItem key={s.id}>
                    <SidebarMenuButton
                      isActive={s.id === scene}
                      onClick={() => setScene(s.id)}
                      tooltip={s.desc}
                    >
                      <span
                        className="w-3 h-3 rounded-sm shrink-0"
                        style={{
                          backgroundColor: s.color,
                          opacity: s.id === scene ? 1 : 0.5,
                        }}
                      />
                      <span>{s.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          <AppSidebarFooter />
        </SidebarFooter>
      </Sidebar>

      {/* Main content */}
      <SidebarInset className="flex flex-row min-w-0">
        {/* Chat */}
        <div className="flex-1 flex flex-col min-w-0">
          <SceneChat
            key={scene}
            scene={scene}
            sceneName={sceneInfo?.label}
            sceneDesc={sceneInfo?.desc}
            sceneColor={sceneInfo?.color}
            sceneGreeting={SCENE_GREETINGS[scene]}
            showPanel={showPanel}
            onTogglePanel={() => setShowPanel(!showPanel)}
          />
        </div>

        {/* Right panel — smooth collapse */}
        <div
          className="flex-shrink-0 overflow-hidden border-l border-sidebar-border bg-sidebar transition-[width] duration-200 ease-in-out"
          style={{ width: showPanel ? "20rem" : "0", borderLeftWidth: showPanel ? "1px" : "0" }}
        >
          <div className="w-80 h-full">
            <PanelView scene={scene} />
          </div>
        </div>
      </SidebarInset>
    </>
  );
}

export default function App() {
  return (
    <TooltipProvider>
      <SidebarProvider>
        <AppInner />
      </SidebarProvider>
    </TooltipProvider>
  );
}
