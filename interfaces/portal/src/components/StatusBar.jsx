import { useState, useEffect } from "react";
import { getStatus } from "../lib/api";

export default function StatusBar() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const data = await getStatus();
        if (mounted) {
          setStatus(data);
          setError(false);
        }
      } catch {
        if (mounted) setError(true);
      }
    };
    check();
    const interval = setInterval(check, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const dot = error
    ? "bg-red-500"
    : status
      ? "bg-green-500"
      : "bg-yellow-500";

  const label = error
    ? "Disconnected"
    : status
      ? "Connected"
      : "Connecting...";

  return (
    <div className="flex items-center justify-between px-4 py-1.5 border-t border-surface-3 bg-surface-1 text-xs text-gray-500">
      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
        <span>{label}</span>
        {status && (
          <>
            <span className="mx-1">|</span>
            <span>
              Store {status.store ? "ok" : "off"} / Events{" "}
              {status.event_bus ? "ok" : "off"} / Plane{" "}
              {status.plane_client ? "ok" : "off"}
            </span>
          </>
        )}
      </div>
      <div>daemon v2.0</div>
    </div>
  );
}
