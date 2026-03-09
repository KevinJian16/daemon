// ── Lexicon: Complete system terminology reference ──
// Source of truth: .ref/TERMINOLOGY.md Part 1 + Part 2 (retained terms)
// System terms are identifiers — never translated in Console.

const LEXICON_DOMAINS = [
  { key: 'psyche', label: 'Psyche \u00b7 \u5fc3\u667a', terms: [
    { term: 'Psyche',   zh: '\u5fc3\u7075\u3002daemon \u7684\u5fc3\u667a\u603b\u79f0\uff0c\u5bb9\u7eb3 Memory / Lore / Instinct\u3002', en: 'The mind. Umbrella for daemon\u2019s knowledge layer: Memory / Lore / Instinct.' },
    { term: 'Memory',   zh: 'daemon \u7684\u8bb0\u5fc6\u3002\u77e5\u8bc6\u5b58\u50a8\u3002', en: 'Daemon\u2019s memory. Persistent knowledge store.' },
    { term: 'Lore',     zh: '\u5b66\u8bc6/\u9605\u5386\u3002daemon \u4ece\u8fc7\u5f80\u7ecf\u9a8c\u4e2d\u79ef\u7d2f\u7684\u667a\u6167\u3002', en: 'Accumulated wisdom from past experience.' },
    { term: 'Instinct', zh: '\u672c\u80fd/\u76f4\u89c9\u3002daemon \u7684\u504f\u597d\u548c\u503e\u5411\u3002', en: 'Preferences and inclinations that guide behavior.' },
  ]},
  { key: 'will', label: 'Will & Action \u00b7 \u610f\u5fd7\u4e0e\u884c\u4e3a', terms: [
    { term: 'Will',     zh: '\u610f\u5fd7\u3002daemon \u901a\u8fc7 Will \u505a\u51fa\u51b3\u7b56\u3001\u9a71\u52a8\u6267\u884c\u3002', en: 'The will. Decision-making and execution driver.' },
    { term: 'Voice',    zh: '\u58f0\u97f3\u3002daemon \u4e0e\u4eba\u5bf9\u8bdd\u7684\u80fd\u529b\u3002', en: 'Daemon\u2019s conversational interface with users.' },
    { term: 'Cadence',  zh: '\u8282\u5f8b\u3002daemon \u7684\u5185\u5728\u8282\u594f\u2014\u2014routine \u8c03\u5ea6\u3002', en: 'Internal rhythm \u2014 routine scheduling and path triggering.' },
    { term: 'Herald',   zh: '\u4f20\u4ee4\u3002daemon \u901a\u8fc7 Herald \u5c06\u6210\u679c\u5e26\u7ed9\u4eba\u3002', en: 'Delivery mechanism that brings results to the user.' },
  ]},
  { key: 'retinue', label: 'Retinue \u00b7 \u968f\u4ece', terms: [
    { term: 'Retinue',   zh: '\u968f\u4ece\u3002\u9884\u521b\u5efa\u7684 agent \u5b9e\u4f8b\u7fa4\uff0cdaemon \u7684\u73ed\u5e95\u3002', en: 'Pre-created agent instance pool. Daemon\u2019s entourage.' },
    { term: 'counsel',   zh: '\u53c2\u8c0b\u3002\u542c\u53d6\u4eba\u7684\u610f\u613f\uff0c\u89c4\u5212\u884c\u52a8\u65b9\u6848\u3002', en: 'Advisor. Understands user intent, plans actions.' },
    { term: 'scout',     zh: '\u659c\u5019\u3002\u5916\u51fa\u6536\u96c6\u60c5\u62a5\u548c\u7d20\u6750\u3002', en: 'Scout. Gathers intelligence and materials.' },
    { term: 'sage',      zh: '\u8d24\u8005\u3002\u6df1\u5ea6\u601d\u8003\u548c\u63a8\u7406\u3002', en: 'Sage. Deep analysis and reasoning.' },
    { term: 'artificer', zh: '\u5de5\u5320\u3002\u6784\u5efa\u4ee3\u7801\u548c\u5de5\u7a0b\u4ea7\u7269\u3002', en: 'Craftsman. Builds code and engineering artifacts.' },
    { term: 'arbiter',   zh: '\u4ef2\u88c1\u3002\u5ba1\u67e5\u8d28\u91cf\uff0c\u5224\u5b9a\u901a\u8fc7\u6216\u91cd\u505a\u3002', en: 'Judge. Reviews quality, decides pass or rework.' },
    { term: 'scribe',    zh: '\u4e66\u8bb0\u3002\u64b0\u5199\u548c\u6392\u7248\u6700\u7ec8\u4ea7\u51fa\u3002', en: 'Scribe. Renders and formats final output.' },
    { term: 'envoy',     zh: '\u4f7f\u8282\u3002\u5c06\u6210\u679c\u5e26\u5f80\u5916\u90e8\u4e16\u754c\u3002', en: 'Envoy. Delivers results to external systems.' },
  ]},
  { key: 'work', label: 'Work \u00b7 \u5de5\u4f5c', terms: [
    { term: 'Brief',    zh: '\u59d4\u6258/\u7b80\u62a5\u3002daemon \u6536\u5230\u7684\u4efb\u52a1\u8bf4\u660e\u3002', en: 'Task specification received by daemon.' },
    { term: 'Design',   zh: '\u6784\u60f3\u3002daemon \u8bbe\u8ba1\u7684\u6267\u884c\u65b9\u6848\uff08DAG\uff09\u3002', en: 'Execution plan (DAG) designed by daemon.' },
    { term: 'Move',     zh: '\u4e00\u7740\u3002Design \u4e2d\u7684\u4e00\u4e2a\u8282\u70b9\uff0cdaemon \u8d70\u7684\u6bcf\u4e00\u6b65\u68cb\u3002', en: 'A single step node in the Design DAG.' },
    { term: 'errand',   zh: '\u5dee\u4e8b\u3002\u6700\u5c0f\u4efb\u52a1\uff0cdaemon \u8dd1\u4e2a\u5c0f\u5dee\u3002', en: 'Smallest task scale. Quick single-shot execution.' },
    { term: 'charge',   zh: '\u804c\u8d23\u3002\u6b63\u5f0f\u59d4\u6258\uff0cdaemon \u53d7\u547d\u800c\u884c\u3002', en: 'Formal assignment. Multi-Move closed-loop delivery.' },
    { term: 'endeavor', zh: '\u4e8b\u4e1a\u3002\u91cd\u5927\u591a\u9636\u6bb5\u4f7f\u547d\uff0cdaemon \u5168\u529b\u4ee5\u8d74\u3002', en: 'Major multi-passage mission with pause/resume.' },
    { term: 'Passage',  zh: '\u5173\u5361\u3002Endeavor \u4e2d\u7684\u9636\u6bb5\u95e8\u69db\u3002', en: 'Phase gate within an Endeavor.' },
  ]},
  { key: 'dominion', label: 'Dominion \u00b7 \u6cbb\u57df', terms: [
    { term: 'Dominion', zh: '\u6cbb\u57df\u3002daemon \u6cbb\u7406\u7684\u9886\u57df\uff0c\u6709\u6ce8\u5165\u8bed\u5883\u3001\u6682\u505c\u6062\u590d\u3001\u9650\u5236\u8d44\u6e90\u7684\u6743\u67c4\u3002', en: 'Governed domain with context injection, pause/resume, and resource control.' },
    { term: 'Writ',     zh: '\u4ee4\u72b6\u3002daemon \u5728\u6cbb\u57df\u4e2d\u5bf9\u968f\u4ece\u53d1\u51fa\u7684\u6d3b\u7684\u6307\u4ee4\u8109\u7edc\u3002', en: 'Live instruction stream within a Dominion \u2014 subscribes events, forks, drives Deeds.' },
    { term: 'Deed',     zh: '\u884c\u4e3e\u3002daemon \u9a71\u4f7f\u968f\u4ece\u5b8c\u6210\u7684\u6bcf\u4e00\u4ef6\u5177\u4f53\u4e8b\u3002\u53ef\u4ee5\u662f errand/charge/endeavor\u3002', en: 'A concrete task executed by the Retinue. Can be errand/charge/endeavor.' },
  ]},
  { key: 'artifacts', label: 'Artifacts \u00b7 \u6210\u679c', terms: [
    { term: 'Offering', zh: '\u732e\u4f5c\u3002daemon \u5c06\u6210\u679c\u732e\u4e88\u4eba\u3002', en: 'Delivered artifacts presented to the user.' },
    { term: 'Vault',    zh: '\u5b9d\u5e93\u3002daemon \u7684\u957f\u671f\u6536\u85cf\u3002', en: 'Long-term archive storage.' },
  ]},
  { key: 'infra', label: 'Infrastructure \u00b7 \u5b58\u5728\u6761\u4ef6', terms: [
    { term: 'Ward',   zh: '\u7ed3\u754c\u3002daemon \u7684\u9632\u62a4\u5c4f\u969c\uff08GREEN / YELLOW / RED\uff09\u3002', en: 'Admission gate: GREEN / YELLOW / RED.' },
    { term: 'Ration', zh: '\u914d\u7ed9\u3002daemon \u7684\u8d44\u6e90\u4efd\u989d\u3002', en: 'Resource quota (daily limits per resource type).' },
    { term: 'Ether',  zh: '\u4ee5\u592a\u3002\u8fde\u63a5 daemon \u53cc\u4f53\uff08API + Worker\uff09\u7684\u7075\u8d28\u3002', en: 'Event bridge connecting daemon\u2019s two processes (API + Worker).' },
    { term: 'Ledger', zh: '\u8d26\u7c3f\u3002daemon \u7684\u72b6\u6001\u8bb0\u5f55\u3002', en: 'Persistent state store.' },
  ]},
  { key: 'spine', label: 'Spine \u00b7 \u81ea\u4e3b\u795e\u7ecf', terms: [
    { term: 'Spine',  zh: 'daemon \u7684\u810a\u67f1\u3002\u81ea\u4e3b\u795e\u7ecf\u7cfb\u7edf\u3002', en: 'Daemon\u2019s backbone. Autonomous nervous system.' },
    { term: 'Nerve',  zh: 'daemon \u7684\u795e\u7ecf\u3002\u4fe1\u53f7\u603b\u7ebf\u3002', en: 'Signal bus for internal events.' },
    { term: 'Cortex', zh: 'daemon \u7684\u76ae\u5c42\u3002LLM \u601d\u8003\u5c42\u3002', en: 'LLM thinking layer. All model calls go through Cortex.' },
    { term: 'Trail',  zh: '\u8e2a\u8ff9\u3002daemon \u5faa\u8e2a\u8ffd\u6eaf\u56e0\u679c\u3002', en: 'Execution trace for debugging and observability.' },
    { term: 'Canon',  zh: '\u5178\u7c4d\u3002routine \u7684\u6b63\u5178\u5b9a\u4e49\u3002', en: 'Canonical routine definitions (the registry).' },
    { term: 'Pact',   zh: '\u5951\u7ea6\u3002IO \u6821\u9a8c\u7684\u7ea6\u5b9a\u3002', en: 'Contracts for input/output validation.' },
  ]},
  { key: 'routines', label: 'Spine Routines \u00b7 \u4f8b\u7a0b', terms: [
    { term: 'pulse',   zh: 'daemon \u611f\u53d7\u8109\u640f\u2014\u2014\u57fa\u7840\u8bbe\u65bd\u5b58\u6d3b\u68c0\u6d4b\u3002', en: 'Heartbeat \u2014 infrastructure liveness check.' },
    { term: 'record',  zh: 'daemon \u8bb0\u5f55\u2014\u2014Deed \u7ed3\u679c\u5199\u5165 Lore\u3002', en: 'Records Deed results into Lore.' },
    { term: 'witness', zh: 'daemon \u89c1\u8bc1\u2014\u2014\u89c2\u5bdf Lore \u8d8b\u52bf\uff0c\u66f4\u65b0 Instinct\u3002', en: 'Observes Lore trends, updates Instinct.' },
    { term: 'learn',   zh: 'daemon \u5b66\u4e60\u2014\u2014\u4ece\u6267\u884c\u4ea7\u51fa\u63d0\u53d6\u77e5\u8bc6\u5199\u5165 Memory\u3002', en: 'Extracts knowledge from execution output into Memory.' },
    { term: 'distill', zh: 'daemon \u63d0\u7eaf\u2014\u2014Memory \u8870\u51cf + \u5bb9\u91cf\u6dd8\u6c70\u3002', en: 'Memory decay and capacity eviction.' },
    { term: 'focus',   zh: 'daemon \u805a\u7126\u2014\u2014\u6ce8\u610f\u529b / embedding \u7d22\u5f15\u7ef4\u62a4\u3002', en: 'Attention and embedding index maintenance.' },
    { term: 'relay',   zh: 'daemon \u4f20\u9012\u2014\u2014Psyche \u5feb\u7167\u5206\u53d1\u81f3 Retinue workspace\u3002', en: 'Distributes Psyche snapshots to Retinue workspaces.' },
    { term: 'tend',    zh: 'daemon \u7167\u6599\u2014\u2014\u6e05\u7406\u3001\u5907\u4efd\u3001\u65e5\u5fd7\u8f6e\u8f6c\u3002', en: 'Cleanup, backup, and log rotation.' },
    { term: 'curate',  zh: 'daemon \u7b56\u5c55\u2014\u2014\u5f52\u6863 deed_root\uff0c\u6e05\u7406\u8fc7\u671f Vault\u3002', en: 'Archives deed_root, cleans expired Vault entries.' },
  ]},
  { key: 'depth', label: 'Depth \u00b7 \u6df1\u5ea6\u7b49\u7ea7', terms: [
    { term: 'glance',   zh: '\u4e00\u77a5\u3002daemon \u5feb\u901f\u5ba1\u89c6\u3002', en: 'Quick scan. Fastest review level.' },
    { term: 'study',    zh: '\u7814\u7a76\u3002daemon \u8ba4\u771f\u5bf9\u5f85\u3002', en: 'Standard review. Thorough analysis.' },
    { term: 'scrutiny', zh: '\u5ba1\u89c6\u3002daemon \u6df1\u5165\u5f7b\u67e5\u3002', en: 'Deep investigation. Most rigorous level.' },
  ]},
  { key: 'skill', label: 'Skill \u00b7 \u80fd\u529b', terms: [
    { term: 'Skill',      zh: 'OpenClaw \u4e13\u6709\u540d\u8bcd\u3002agent \u7684\u53ef\u88c5\u8f7d\u80fd\u529b\u5355\u5143\uff0cSKILL.md \u4e3a\u6743\u5a01\u3002', en: 'Loadable capability unit for agents. SKILL.md is source of truth.' },
    { term: 'skill_type', zh: 'capability\uff08\u80fd\u529b\uff09\u6216 preference\uff08\u504f\u597d\uff09\u3002', en: 'Classification: capability or preference.' },
  ]},
  { key: 'interface', label: 'Interface \u00b7 \u754c\u9762', terms: [
    { term: 'Portal',   zh: 'daemon \u7684\u95e8\u6237\u3002\u7528\u6237\u754c\u9762\u3002', en: 'User-facing interface.' },
    { term: 'Console',  zh: 'daemon \u7684\u63a7\u5236\u53f0\u3002\u8fd0\u7ef4\u754c\u9762\u3002', en: 'Operations interface (this tool).' },
  ]},
  { key: 'status', label: 'Status \u00b7 \u72b6\u6001\u8bcd\u6c47', terms: [
    { term: 'deed_status',     zh: 'queued / running / paused / completed / failed / cancelled / awaiting_eval / pending_review', en: 'Deed lifecycle states.' },
    { term: 'move_status',     zh: 'ok / degraded / error / rework / circuit_breaker / cancelled', en: 'Move execution result states.' },
    { term: 'dominion_status', zh: 'active / paused / completed / abandoned', en: 'Dominion lifecycle states.' },
    { term: 'writ_status',     zh: 'active / paused / disabled', en: 'Writ lifecycle states.' },
    { term: 'endeavor_status', zh: '\u540c deed_status\uff0c\u5916\u52a0 phase \u5b57\u6bb5\u6807\u8bc6\u5f53\u524d\u9636\u6bb5\u3002', en: 'Same as deed_status, plus phase field for current stage.' },
    { term: 'passage_status',  zh: 'Endeavor Passage \u7684\u7ed3\u679c\u72b6\u6001\u3002', en: 'Endeavor Passage result status.' },
  ]},
  { key: 'model_alias', label: 'Model Aliases \u00b7 \u6a21\u578b\u522b\u540d', terms: [
    { term: 'fast',      zh: '\u5feb\u901f\u6a21\u578b\u3002counsel/scout/artificer/envoy \u9ed8\u8ba4\u3002', en: 'Fast model. Default for counsel/scout/artificer/envoy.' },
    { term: 'analysis',  zh: '\u5206\u6790\u6a21\u578b\u3002sage \u9ed8\u8ba4\u3002', en: 'Analysis model. Default for sage.' },
    { term: 'review',    zh: '\u5ba1\u67e5\u6a21\u578b\u3002arbiter \u9ed8\u8ba4\u3002', en: 'Review model. Default for arbiter.' },
    { term: 'glm',       zh: 'GLM \u6a21\u578b\u3002scribe \u9ed8\u8ba4\u3002', en: 'GLM model. Default for scribe.' },
    { term: 'embedding', zh: 'Embedding \u6a21\u578b\u3002focus routine \u4f7f\u7528\u3002', en: 'Embedding model. Used by focus routine.' },
  ]},
  { key: 'derived', label: 'Naming Conventions \u00b7 \u6d3e\u751f\u540e\u7f00', terms: [
    { term: '_id',         zh: '\u552f\u4e00\u6807\u8bc6\u3002\u5982 deed_id, dominion_id, writ_id\u3002', en: 'Unique identifier. e.g. deed_id, dominion_id.' },
    { term: 'Config',      zh: '\u9759\u6001\u5b9a\u4e49\u3002\u5982 DominionConfig, WritConfig\u3002', en: 'Static definition. e.g. DominionConfig.' },
    { term: '_status',     zh: '\u8fd0\u884c\u65f6\u72b6\u6001\u3002\u5982 deed_status, writ_status\u3002', en: 'Runtime state. e.g. deed_status.' },
    { term: '_completed',  zh: '\u5b8c\u6210\u4e8b\u4ef6\u3002\u5982 deed_completed, herald_completed\u3002', en: 'Completion event. e.g. deed_completed.' },
    { term: '_failed',     zh: '\u5931\u8d25\u4e8b\u4ef6\u3002\u5982 deed_failed\u3002', en: 'Failure event. e.g. deed_failed.' },
    { term: '_root',       zh: '\u6587\u4ef6\u7cfb\u7edf\u76ee\u5f55\u3002\u5982 deed_root, offering_root\u3002', en: 'File system directory. e.g. deed_root.' },
    { term: 'work_scale',  zh: '\u6267\u884c\u89c4\u6a21\u5f62\u6001\uff1aerrand / charge / endeavor\u3002', en: 'Execution scale: errand / charge / endeavor.' },
    { term: 'deed_type',   zh: '\u6267\u884c\u6a21\u677f\u952e\uff0c\u7528\u4e8e\u5339\u914d Lore recipe \u548c\u8d28\u91cf\u89c4\u5219\u3002', en: 'Execution template key for matching Lore recipes and quality rules.' },
    { term: 'provider_route', zh: '\u6a21\u578b\u63d0\u4f9b\u65b9\u56de\u9000\u8def\u5f84\u3002', en: 'Provider fallback path for model routing.' },
  ]},
];

registerPanel('lexicon', {
  async load() {},
  render() {
    return LEXICON_DOMAINS.map(d => `
      <div class="list-item" onclick="PANELS.lexicon.openDetail('${esc(d.key)}')">
        <div class="item-main">
          <div class="item-title">${esc(d.label)}</div>
          <div class="item-sub">${d.terms.length} terms</div>
        </div>
      </div>
    `).join('');
  },
  openDetail(key) {
    const d = LEXICON_DOMAINS.find(x => x.key === key);
    if (!d) return;
    const html = d.terms.map(t => `
      <div class="sub-item">
        <div class="item-main">
          <div class="item-title">${esc(t.term)}</div>
          <div class="item-sub">${esc(cLang === 'zh' ? t.zh : t.en)}</div>
        </div>
      </div>
    `).join('');
    pushDetail(d.label, html);
  }
});
