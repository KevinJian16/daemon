import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import ClaudeSidebar from "./components/ClaudeSidebar";
import DeskPage from "./components/DeskPage";
import FolioPage from "./components/FolioPage";
import SlipPage from "./components/SlipPage";
import { getDrafts, getSidebar } from "./lib/api";

function PortalLayout({
  sidebar,
  sidebarLoading,
  sidebarError,
  drafts,
  draftsLoading,
  refreshSidebar,
  refreshDrafts,
  lastWsEvent,
}) {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");

  return (
    <div className="flex h-full bg-[#F5F5F0]">
      <ClaudeSidebar
        sidebar={sidebar}
        loading={sidebarLoading}
        error={sidebarError}
        drafts={drafts}
        draftsLoading={draftsLoading}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((current) => !current)}
        search={search}
        onSearchChange={setSearch}
        pathname={location.pathname}
      />
      <main className="min-w-0 flex-1">
        <Outlet context={{ sidebar, sidebarLoading, drafts, draftsLoading, refreshSidebar, refreshDrafts, lastWsEvent }} />
      </main>
    </div>
  );
}

function PortalApp() {
  const [sidebar, setSidebar] = useState(null);
  const [sidebarLoading, setSidebarLoading] = useState(true);
  const [sidebarError, setSidebarError] = useState("");
  const [drafts, setDrafts] = useState([]);
  const [draftsLoading, setDraftsLoading] = useState(true);
  const [lastWsEvent, setLastWsEvent] = useState(null);
  const sidebarLoadedRef = useRef(false);
  const draftsLoadedRef = useRef(false);

  const refreshSidebar = useCallback(async () => {
    const shouldShowLoading = !sidebarLoadedRef.current;
    if (shouldShowLoading) {
      setSidebarLoading(true);
    }
    setSidebarError("");
    try {
      const payload = await getSidebar();
      setSidebar(payload);
      sidebarLoadedRef.current = true;
    } catch (error) {
      setSidebarError(error.message || "侧栏装载失败。");
    } finally {
      if (shouldShowLoading) {
        setSidebarLoading(false);
      }
    }
  }, []);

  const refreshDrafts = useCallback(async () => {
    const shouldShowLoading = !draftsLoadedRef.current;
    if (shouldShowLoading) {
      setDraftsLoading(true);
    }
    try {
      const payload = await getDrafts();
      setDrafts(Array.isArray(payload) ? payload : []);
      draftsLoadedRef.current = true;
    } finally {
      if (shouldShowLoading) {
        setDraftsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refreshSidebar();
    refreshDrafts();
  }, [refreshDrafts, refreshSidebar]);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
    let heartbeat = 0;

    socket.addEventListener("open", () => {
      heartbeat = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send("ping");
        }
      }, 15_000);
    });

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        setLastWsEvent(payload);
        if (payload?.event === "ping" && socket.readyState === WebSocket.OPEN) {
          socket.send("ping");
          return;
        }
        if (
          [
            "deed_closed",
            "deed_failed",
            "deed_settling",
            "folio_progress_update",
            "ward_changed",
            "draft_created",
            "draft_updated",
            "draft_crystallized",
          ].includes(String(payload?.event || ""))
        ) {
          refreshSidebar();
        }
        if (["draft_created", "draft_updated", "draft_crystallized"].includes(String(payload?.event || ""))) {
          refreshDrafts();
        }
      } catch {
        // Ignore malformed frames in the Portal shell.
      }
    });

    return () => {
      if (heartbeat) {
        window.clearInterval(heartbeat);
      }
      socket.close();
    };
  }, [refreshDrafts, refreshSidebar]);

  return (
    <Routes>
      <Route
        path="/"
        element={
          <PortalLayout
            sidebar={sidebar}
            sidebarLoading={sidebarLoading}
            sidebarError={sidebarError}
            drafts={drafts}
            draftsLoading={draftsLoading}
            refreshSidebar={refreshSidebar}
            refreshDrafts={refreshDrafts}
            lastWsEvent={lastWsEvent}
          />
        }
      >
        <Route index element={<DeskPage />} />
        <Route path="slips/:slipSlug" element={<SlipPage />} />
        <Route path="slips/:slipSlug/deeds/:deedId" element={<SlipPage />} />
        <Route path="folios/:folioSlug" element={<FolioPage />} />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename="/portal">
      <PortalApp />
    </BrowserRouter>
  );
}
