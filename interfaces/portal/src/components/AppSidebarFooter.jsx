import { useState, useEffect } from "react";
import { getStatus } from "../lib/api";

export default function AppSidebarFooter() {
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

  const dotColor = error ? "bg-red-500" : status ? "bg-emerald-500" : "bg-amber-500";
  const label = error ? "Disconnected" : status ? "Connected" : "Connecting...";

  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span>{label}</span>
    </div>
  );
}
