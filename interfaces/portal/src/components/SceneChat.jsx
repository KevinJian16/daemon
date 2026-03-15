import { useState, useCallback } from "react";
import MessageThread from "./MessageThread";
import Composer from "./Composer";
import JobNotice from "./JobNotice";
import { sendMessage } from "../lib/api";

let msgCounter = 0;

export default function SceneChat({ scene }) {
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

        // Track jobs created by L1
        if (res.job_id) {
          setPendingJobs((prev) => [
            ...prev,
            {
              job_id: res.job_id,
              action: res.action,
              created_at: new Date().toISOString(),
            },
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

  return (
    <div className="flex flex-col h-full">
      {/* Job notices */}
      {pendingJobs.length > 0 && (
        <div className="px-4 pt-2 space-y-2">
          {pendingJobs.map((job) => (
            <JobNotice key={job.job_id} job={job} onDismiss={dismissJob} />
          ))}
        </div>
      )}

      {/* Messages */}
      <MessageThread messages={messages} isLoading={isLoading} />

      {/* Composer */}
      <Composer onSend={handleSend} disabled={isLoading} />
    </div>
  );
}
