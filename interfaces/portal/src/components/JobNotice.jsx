import { useState, useEffect } from "react";
import { listJobs } from "../lib/api";

const STATUS_COLORS = {
  running: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  closed: "bg-green-500/20 text-green-300 border-green-500/30",
  failed: "bg-red-500/20 text-red-300 border-red-500/30",
};

export default function JobNotice({ job, onDismiss }) {
  const [status, setStatus] = useState("running");

  // Poll job status
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
  const colorClass = STATUS_COLORS[status] || STATUS_COLORS.running;

  return (
    <div
      className={`flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${colorClass}`}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">{actionType}</span>
        <span className="text-gray-400">|</span>
        <span>{title}</span>
        <span className="opacity-60">({status})</span>
      </div>
      <button
        onClick={() => onDismiss(job.job_id)}
        className="text-gray-500 hover:text-gray-300 ml-2"
      >
        &times;
      </button>
    </div>
  );
}
