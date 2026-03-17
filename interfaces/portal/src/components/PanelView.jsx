import { useState, useEffect } from "react";
import { getPanel } from "../lib/api";
import { Button } from "@/components/ui/button";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";

function Section({ title, children, count }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider mb-2 text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? (
          <ChevronDownIcon className="w-3 h-3" />
        ) : (
          <ChevronRightIcon className="w-3 h-3" />
        )}
        <span>{title}</span>
        {count != null && (
          <span className="text-muted-foreground/50">({count})</span>
        )}
      </button>
      {open && children}
    </div>
  );
}

function timeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function PanelView({ scene }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const d = await getPanel(scene);
        if (mounted) setData(d);
      } catch (err) {
        if (mounted) setError(err.message);
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [scene]);

  if (error) {
    return (
      <div className="p-4 text-xs text-muted-foreground">
        Panel unavailable: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4 text-xs text-muted-foreground">Loading panel...</div>
    );
  }

  const digests = data.digests || [];
  const decisions = data.decisions || [];

  return (
    <div className="p-4 overflow-y-auto h-full text-sm">
      <Section title="Digests" count={digests.length}>
        {digests.length === 0 ? (
          <p className="text-xs text-muted-foreground">No digests yet.</p>
        ) : (
          <div className="space-y-2">
            {digests.map((d, i) => (
              <div key={d.digest_id || i} className="rounded-lg bg-muted p-3 text-xs">
                <div className="mb-1 text-muted-foreground">
                  {timeAgo(d.time_range_end)} &middot; {d.source_message_count || "?"} msgs
                </div>
                <div className="text-foreground whitespace-pre-wrap">{d.summary}</div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Decisions" count={decisions.length}>
        {decisions.length === 0 ? (
          <p className="text-xs text-muted-foreground">No decisions yet.</p>
        ) : (
          <div className="space-y-2">
            {decisions.map((d, i) => (
              <div key={d.decision_id || i} className="rounded-lg bg-muted p-3 text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium uppercase bg-primary/10 text-primary">
                    {d.decision_type}
                  </span>
                  <span className="text-muted-foreground">{timeAgo(d.created_at)}</span>
                </div>
                <div className="text-foreground">{d.content}</div>
                {d.tags?.length > 0 && (
                  <div className="flex gap-1 mt-1.5">
                    {d.tags.map((t) => (
                      <span
                        key={t}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-accent text-accent-foreground"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
