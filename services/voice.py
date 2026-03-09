"""Voice Service — Counsel Agent conversation management."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from runtime.brief import Brief

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class VoiceService:
    """Manages conversational sessions with the Counsel Agent via OpenClaw Gateway."""

    SESSION_TTL_S = 24 * 3600

    def __init__(
        self,
        instinct: "InstinctPsyche",
        openclaw_home: Path | None = None,
        dominion_writ_manager: Any | None = None,
        cortex: Any | None = None,
    ) -> None:
        self._instinct = instinct
        self._oc_home = openclaw_home
        self._dominion_writ = dominion_writ_manager
        self._cortex = cortex
        self._oc_cfg: dict | None = None
        self._sessions: dict[str, dict] = {}
        if openclaw_home:
            cfg_path = openclaw_home / "openclaw.json"
            if cfg_path.exists():
                try:
                    self._oc_cfg = json.loads(cfg_path.read_text())
                except Exception as exc:
                    logger.warning("Failed to load openclaw config from %s: %s", cfg_path, exc)

    def new_session(self, user_id: str = "default") -> str:
        self._cleanup_sessions()
        session_id = f"voice_{uuid.uuid4().hex[:10]}"
        self._sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_utc": _utc(),
            "last_active_ts": time.time(),
            "messages": [],
        }
        return session_id

    def chat(self, session_id: str, message: str) -> dict:
        """Send a message to the Counsel Agent and return its response."""
        self._cleanup_sessions()
        if session_id not in self._sessions:
            return {"ok": False, "error": "session_not_found"}

        session = self._sessions[session_id]
        session["last_active_ts"] = time.time()
        session["messages"].append({"role": "user", "content": message, "timestamp": _utc()})

        direct = self._handle_long_horizon_command(message)
        if direct is not None:
            session["messages"].append({"role": "assistant", "content": direct["content"], "timestamp": _utc()})
            return {**direct, "session_id": session_id}

        if not self._oc_cfg:
            return {"ok": False, "error": "OpenClaw not configured"}

        # Keep daemon-only fallback to avoid accidentally binding old MAS defaults.
        gw_port = self._oc_cfg.get("gateway", {}).get("port", 18790)
        gw_token = self._oc_cfg.get("gateway", {}).get("auth", {}).get("token", "")
        gw_url = f"http://127.0.0.1:{gw_port}"
        headers = {"Authorization": f"Bearer {gw_token}", "Content-Type": "application/json"}

        # Build session key for counsel.
        oc_session_key = f"agent:counsel:voice:{session_id}"

        try:
            resp = httpx.post(
                f"{gw_url}/tools/invoke",
                json={
                    "tool": "sessions_send",
                    "args": {"sessionKey": oc_session_key, "agentId": "counsel", "message": message},
                },
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            send_result = resp.json().get("result") or {}
            send_details = send_result.get("details") or {}
            send_status = str(send_details.get("status") or "").strip().lower()
            if send_status in {"error", "forbidden", "failed"}:
                err = str(send_details.get("error") or send_details.get("message") or send_status)
                return {"ok": False, "error": err}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        # Poll for response (up to 60s for voice).
        deadline = time.time() + 60
        last_content = ""
        while time.time() < deadline:
            time.sleep(2)
            try:
                hist = httpx.post(
                    f"{gw_url}/tools/invoke",
                    json={"tool": "sessions_history", "args": {"sessionKey": oc_session_key, "limit": 1}},
                    headers=headers,
                    timeout=15,
                )
                hist.raise_for_status()
                data = hist.json()
                result = data.get("result") or {}
                details = result.get("details") or {}
                status = str(details.get("status") or "").strip().lower()
                if status in {"error", "forbidden", "failed"}:
                    continue
                messages = details.get("messages") or result.get("messages") or []
                latest = messages[-1] if messages else {}
                content = self._extract_message_text(latest)
                if latest.get("role") == "assistant" and content and content != last_content:
                    last_content = content
                    session["messages"].append({"role": "assistant", "content": content, "timestamp": _utc()})

                    # Check for plan extraction.
                    plan = self._extract_plan(content)
                    if plan:
                        plan = self._enrich_plan(plan, session=session, latest_message=message)
                    brief_summary = self._brief_summary(plan)
                    return {
                        "ok": True,
                        "content": content,
                        "session_id": session_id,
                        "plan": plan,
                        "brief_summary": brief_summary,
                    }
            except Exception as exc:
                logger.error("Voice chat error for session %s: %s", session_id, exc)

        return {"ok": False, "error": "voice_timeout", "session_id": session_id}

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def _extract_plan(self, content: str) -> dict | None:
        """Try to extract a structured plan from Counsel response and validate convergence."""
        if "```json" not in content:
            return None
        try:
            start = content.index("```json") + 7
            end = content.index("```", start)
            raw = content[start:end].strip()
            plan = json.loads(raw)
            if not isinstance(plan, dict) or not plan.get("moves"):
                return None
            if not isinstance(plan.get("brief"), dict):
                brief = Brief(
                    objective=str(plan.get("objective") or plan.get("title") or plan.get("charge_title") or ""),
                    complexity=str(plan.get("complexity") or plan.get("work_scale") or "charge"),
                    language=str(plan.get("language") or plan.get("output_lang") or "bilingual"),
                    format=str(plan.get("format") or plan.get("deliverable") or "markdown"),
                    depth=str(plan.get("depth") or "study"),
                )
                plan["brief"] = brief.to_dict()
            # Convergence validation: DAG must be valid before surfacing.
            valid, err = self._validate_plan_convergence(plan)
            if not valid:
                logger.info("Voice plan failed convergence: %s", err)
                plan["_convergence_error"] = err
            else:
                plan["_convergence_validated"] = True
            return plan
        except Exception as exc:
            logger.debug("_extract_plan: failed to parse JSON plan: %s", exc)
        return None

    @staticmethod
    def _validate_plan_convergence(plan: dict) -> tuple[bool, str]:
        """Validate plan DAG for convergence: no cycles, valid agents, terminal moves."""
        moves = plan.get("moves") or []
        if not isinstance(moves, list) or not moves:
            return False, "empty moves"
        valid_agents = {"scout", "sage", "artificer", "arbiter", "scribe", "envoy", "counsel", "spine"}
        ids: set[str] = set()
        normalized: list[tuple[str, dict]] = []
        for i, st in enumerate(moves):
            if not isinstance(st, dict):
                return False, f"move {i} not a dict"
            sid = str(st.get("id") or f"move_{i}")
            if sid in ids:
                return False, f"duplicate id: {sid}"
            ids.add(sid)
            normalized.append((sid, st))
            agent = str(st.get("agent") or "")
            if agent and agent not in valid_agents:
                return False, f"unknown agent: {agent}"
        for sid, st in normalized:
            for dep in st.get("depends_on") or []:
                if dep not in ids:
                    return False, f"move {sid} depends on unknown {dep}"
        brief = plan.get("brief") or {}
        ration = int(brief.get("move_ration") or 999)
        if len(moves) > ration:
            return False, f"moves {len(moves)} > ration {ration}"
        terminal = [s for s in moves if not any(
            str(s.get("id") or "") in (other.get("depends_on") or [])
            for other in moves if other is not s
        )]
        if not terminal:
            return False, "no terminal moves (possible cycle)"
        return True, ""

    def _extract_message_text(self, msg: dict) -> str:
        raw = msg.get("content")
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            chunks = []
            for item in raw:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text)
            if chunks:
                return "\n".join(chunks).strip()
        text = msg.get("text")
        if isinstance(text, str):
            return text
        err = msg.get("errorMessage")
        if isinstance(err, str):
            return err
        return ""

    def _cleanup_sessions(self) -> None:
        cutoff = time.time() - self.SESSION_TTL_S
        stale = [
            sid for sid, row in self._sessions.items()
            if float(row.get("last_active_ts") or 0.0) < cutoff
        ]
        for sid in stale:
            self._sessions.pop(sid, None)

    def _enrich_plan(self, plan: dict, *, session: dict, latest_message: str) -> dict:
        out = dict(plan)
        brief = Brief.from_dict(out.get("brief") if isinstance(out.get("brief"), dict) else {})
        metadata = out.get("metadata") if isinstance(out.get("metadata"), dict) else {}
        out["brief"] = brief.to_dict()
        deed_title = str(out.get("deed_title") or out.get("title") or out.get("charge_title") or "").strip()
        if not deed_title:
            deed_title = self._generate_title(brief.objective or latest_message)
        out["deed_title"] = deed_title
        out["title"] = deed_title

        affinity = self._dominions_for_text(brief.objective or latest_message)
        if affinity and not str(metadata.get("dominion_id") or "").strip():
            metadata["dominion_id"] = str(affinity[0].get("dominion_id") or "")
        trigger = self._detect_recurring_trigger(latest_message)
        if trigger and not str(metadata.get("writ_id") or "").strip():
            metadata.setdefault("create_dominion_objective", brief.objective or deed_title)
            metadata.setdefault("create_writ_label", deed_title)
            metadata.setdefault("create_writ_trigger", trigger)
        out["metadata"] = metadata
        out["complexity"] = brief.complexity
        out["plan_display"] = self._display_metadata(brief, out)
        return out

    def _display_metadata(self, brief: Brief, plan: dict) -> dict:
        moves = plan.get("moves") if isinstance(plan.get("moves"), list) else []
        complexity = brief.complexity
        if complexity == "errand":
            return {
                "mode": "errand",
                "show_timeline": False,
                "summary": brief.objective,
                "moves": [{"id": str(row.get("id") or ""), "agent": str(row.get("agent") or "")} for row in moves[:3]],
            }
        if complexity == "endeavor":
            passages = plan.get("passages") if isinstance(plan.get("passages"), list) else []
            return {
                "mode": "endeavor",
                "show_timeline": False,
                "passages": [
                    {
                        "title": str(row.get("title") or f"Passage {idx + 1}"),
                        "move_count": len(row.get("move_ids") or row.get("moves") or []),
                    }
                    for idx, row in enumerate(passages)
                    if isinstance(row, dict)
                ],
            }
        return {
            "mode": "charge",
            "show_timeline": True,
            "timeline": [
                {
                    "id": str(row.get("id") or ""),
                    "agent": str(row.get("agent") or ""),
                    "label": str(row.get("instruction") or row.get("message") or "")[:80],
                }
                for row in moves
                if isinstance(row, dict)
            ],
        }

    def _brief_summary(self, plan: dict | None) -> str:
        if not isinstance(plan, dict):
            return ""
        brief = Brief.from_dict(plan.get("brief") if isinstance(plan.get("brief"), dict) else {})
        refs = len(brief.references or [])
        return f"{brief.objective} | {brief.complexity} | {brief.depth} | {brief.language} | refs={refs}"

    def _generate_title(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if not compact:
            return "Untitled Deed"
        if self._cortex and self._cortex.is_available():
            try:
                prompt = (
                    "Generate one concise Deed title in the same language as the request. "
                    "Return plain text only, under 18 words.\n\n"
                    f"Request:\n{compact[:800]}"
                )
                candidate = str(self._cortex.complete(prompt, max_tokens=40, temperature=0.2) or "").strip()
                candidate = candidate.splitlines()[0].strip(" -#*")
                if candidate:
                    return candidate[:120]
            except Exception:
                pass
        return compact[:60]

    def _dominions_for_text(self, text: str) -> list[dict]:
        if not self._dominion_writ:
            return []
        try:
            return self._dominion_writ.active_dominion_matches(text, limit=3)
        except Exception:
            return []

    def _detect_recurring_trigger(self, message: str) -> dict | None:
        text = str(message or "").lower()
        if not text:
            return None
        schedule = ""
        if any(token in text for token in ["每天", "daily", "every day"]):
            schedule = "0 9 * * *"
        elif any(token in text for token in ["每周", "weekly", "every week"]):
            schedule = "0 9 * * 1"
        elif any(token in text for token in ["每月", "monthly", "every month"]):
            schedule = "0 9 1 * *"
        if not schedule:
            return None
        return {"schedule": schedule}

    def _handle_long_horizon_command(self, message: str) -> dict | None:
        if not self._dominion_writ:
            return None
        raw = str(message or "").strip()
        lowered = raw.lower()
        matches = self._dominions_for_text(raw)
        target = matches[0] if matches else None
        if target and any(token in lowered for token in ["不用看了", "停止跟踪", "stop tracking", "stop monitoring"]):
            count = 0
            for writ in self._dominion_writ.list_writs(dominion_id=str(target.get("dominion_id") or "")):
                if str(writ.get("status") or "") != "disabled":
                    self._dominion_writ.update_writ(str(writ.get("writ_id") or ""), {"status": "disabled"})
                    count += 1
            return {"ok": True, "content": f"已停止该长期关注线的自动推进，关闭了 {count} 条活动 Writ。"}
        trigger = self._detect_recurring_trigger(raw)
        if target and trigger and any(token in lowered for token in ["改成", "调整为", "switch to", "change to"]):
            updated = 0
            for writ in self._dominion_writ.list_writs(dominion_id=str(target.get("dominion_id") or "")):
                self._dominion_writ.update_writ(str(writ.get("writ_id") or ""), {"trigger": {**(writ.get("trigger") or {}), **trigger}})
                updated += 1
            return {"ok": True, "content": f"已调整该长期关注线的节律，更新了 {updated} 条 Writ。"}
        return None
