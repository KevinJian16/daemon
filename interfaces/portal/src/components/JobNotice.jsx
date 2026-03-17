import { useState, useEffect } from "react";
import { listJobs } from "../lib/api";

const STATUS_STYLES = {
  running: {
    background: "rgba(99, 102, 241, 0.08)",
    color: "#6366f1",
    border: "1px solid rgba(99, 102, 241, 0.2)",
  },
  closed: {
    background: "rgba(5, 150, 105, 0.08)",
    color: "#059669",
    border: "1px solid rgba(5, 150, 105, 0.2)",
  },
  failed: {
    background: "rgba(220, 38, 38, 0.08)",
    color: "#dc2626",
    border: "1px solid rgba(220, 38, 38, 0.2)",
  },
};

export default function JobNotice({ job, onDismiss }) {
  const [status, setStatus] = useState("running");

  useEffect(() => {
    if (status !== "running") return;
    const interval = setInterval(async () => {
      try {
        const jobs = await listJobs("", 50);
        const found = (Array.isArray(jobs) ? jobs : jobs.jobs || []).find(
          (j) => j.job_id === job.job_id,
        );
        if (found && found.status !== "running") {
          setStatus(found.sub_status || found.status);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [job.job_id, status]);

  const actionType = job.action?.action || "job";
  const title = job.action?.title || `Job ${job.job_id.slice(0, 8)}`;
  const style = STATUS_STYLES[status] || STATUS_STYLES.running;

  return (
    <div
      className="flex items-center justify-between rounded-lg px-3 py-2 text-xs animate-fade-in"
      style={style}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">{actionType}</span>
        <span style={{ color: "var(--text-tertiary)" }}>|</span>
        <span>{title}</span>
        <span className="opacity-60">({status})</span>
      </div>
      <button
        onClick={() => onDismiss(job.job_id)}
        className="ml-2 transition-colors"
        style={{ color: "var(--text-tertiary)" }}
      >
        &times;
      </button>
    </div>
  );
}
