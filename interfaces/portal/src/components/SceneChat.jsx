import { useState, useCallback } from "react";
import { useSidebar } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { PanelLeftIcon, PanelRightIcon } from "lucide-react";
import MessageThread from "./MessageThread";
import Composer from "./Composer";
import JobNotice from "./JobNotice";
import { sendMessage } from "../lib/api";

let msgCounter = 0;

export default function SceneChat({
  scene,
  sceneName,
  sceneDesc,
  sceneColor,
  sceneGreeting,
  showPanel,
  onTogglePanel,
}) {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [pendingJobs, setPendingJobs] = useState([]);

  const handleSend = useCallback(
    async (content) => {
      const userMsg = {
        id: `msg-${++msgCounter}`,
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);

      try {
        const res = await sendMessage(scene, content);
        const assistantMsg = {
          id: `msg-${++msgCounter}`,
          role: "assistant",
          content: res.reply || "(no response)",
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);

        if (res.job_id) {
          setPendingJobs((prev) => [
            ...prev,
            { job_id: res.job_id, action: res.action, created_at: new Date().toISOString() },
          ]);
        }
      } catch (err) {
        const errMsg = {
          id: `msg-${++msgCounter}`,
          role: "system",
          content: `Error: ${err.message}`,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    [scene],
  );

  const dismissJob = useCallback((jobId) => {
    setPendingJobs((prev) => prev.filter((j) => j.job_id !== jobId));
  }, []);

  const { toggleSidebar, open: sidebarOpen } = useSidebar();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center justify-between h-12 px-4 shrink-0 border-b border-border">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={toggleSidebar}
            className={sidebarOpen ? "text-primary" : "text-muted-foreground"}
          >
            <PanelLeftIcon className="h-4 w-4" />
          </Button>
          <span className="flex items-baseline gap-2">
            <span className="text-sm font-medium">{sceneName}</span>
            <span className="text-xs text-muted-foreground hidden sm:inline">{sceneDesc}</span>
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onTogglePanel}
          className={showPanel ? "text-primary" : "text-muted-foreground"}
        >
          <PanelRightIcon className="h-4 w-4" />
        </Button>
      </header>

      {/* Job notices */}
      {pendingJobs.length > 0 && (
        <div className="px-5 pt-2.5 space-y-1.5 max-w-2xl mx-auto w-full">
          {pendingJobs.map((job) => (
            <JobNotice key={job.job_id} job={job} onDismiss={dismissJob} />
          ))}
        </div>
      )}

      {/* Messages */}
      <MessageThread
        messages={messages}
        isLoading={isLoading}
        sceneName={sceneName}
        sceneGreeting={sceneGreeting}
        sceneColor={sceneColor}
        sceneDesc={sceneDesc}
      />

      {/* Composer */}
      <Composer onSend={handleSend} disabled={isLoading} sceneName={sceneName} sceneColor={sceneColor} />
    </div>
  );
}
