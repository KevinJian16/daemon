# Scene API Endpoints

The Scene API provides endpoints for interacting with L1 (Level 1) agents in different scenes. Scenes represent different agent roles: `copilot`, `mentor`, `coach`, `operator`.

Reference: SYSTEM_DESIGN.md §5.1

---

## POST /scenes/{scene}/chat

Send a message to a scene's L1 agent.

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `scene` | string | Scene name: `copilot`, `mentor`, `coach`, `operator` |

### Request Body

```json
{
  "content": "string (required)",
  "metadata": { "key": "value" } | null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | string | The message to send to the L1 agent |
| `metadata` | object? | Optional metadata to attach to the message |

### Response

```json
{
  "ok": true,
  "scene": "copilot",
  "reply": "Agent response text...",
  "action": {
    "action": "create_job",
    "steps": [...]
  } | null,
  "job_id": "uuid-string" | null,
  "error": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Whether the request succeeded |
| `scene` | string | The scene that processed the message |
| `reply` | string | The L1 agent's response text |
| `action` | object? | Structured action if L1 agent triggered one (see below) |
| `job_id` | string? | UUID of created job if action was dispatched |
| `error` | string? | Error message if `ok` is false |

### L1 Agent Actions

The L1 agent may return a structured action to dispatch work to L2:

| Action Type | Description |
|-------------|-------------|
| `create_job` / `task` / `project` | Creates a multi-step Job submitted to Temporal |
| `direct` | Creates a single-step direct Job (lightweight) |
| `direct_response` / null | Direct text reply, no job created |

### Example

```bash
curl -X POST http://localhost:8000/scenes/copilot/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Create a new API endpoint for user preferences"}'
```

---

## GET /scenes/{scene}/panel

Get scene panel data including recent messages, digests, and decisions.

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `scene` | string | Scene name: `copilot`, `mentor`, `coach`, `operator` |

### Response

```json
{
  "scene": "copilot",
  "messages": [
    {
      "message_id": "uuid",
      "scene": "copilot",
      "role": "user",
      "content": "Message text...",
      "token_count": 10,
      "user_id": "default",
      "created_at": "2026-03-15T10:30:00Z"
    }
  ],
  "digests": [
    {
      "digest_id": "uuid",
      "scene": "copilot",
      "time_range_start": "2026-03-01T00:00:00Z",
      "time_range_end": "2026-03-15T00:00:00Z",
      "summary": "Digest summary text...",
      "source_message_count": 50
    }
  ],
  "decisions": [
    {
      "decision_id": "uuid",
      "scene": "copilot",
      "decision_type": "architecture",
      "content": "Decision text...",
      "context_summary": "Context...",
      "tags": ["database"],
      "created_at": "2026-03-15T09:00:00Z"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `scene` | string | The scene identifier |
| `messages` | array | Recent messages (up to 20), chronologically ordered |
| `digests` | array | Recent compressed digests (up to 5) |
| `decisions` | array | Recent extracted decisions (up to 10) |

### Example

```bash
curl http://localhost:8000/scenes/copilot/panel
```

---

## WebSocket: /scenes/{scene}/chat/stream

Real-time chat via WebSocket for continuous L1 agent interaction.

### Protocol

**Client → Server:**
```json
{"content": "user message"}
```

**Server → Client ( replies):**
```json
{"type": "reply", "content": "agent response...", "scene": "copilot"}
```

**Server → Client (actions):**
```json
{"type": "action", "action": {"action": "create_job", "steps": [...]}}
```

**Server → Client (errors):**
```json
{"type": "error", "error": "error message"}
```

### Example

```javascript
const ws = new WebSocket('ws://localhost:8000/scenes/copilot/chat/stream');
ws.onmessage = (event) => console.log(JSON.parse(event.data));
ws.send(JSON.stringify({ content: "Hello!" }));
```
