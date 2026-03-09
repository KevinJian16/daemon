const LEXICON_ROWS = [
  {
    term: 'Deed',
    type: 'execution',
    zh: '一次可追踪的执行实例。系统状态、评价、产物都挂在 Deed 上，不挂在需求文本上。',
    en: 'A traceable execution instance. State, feedback, and offerings are bound to deed, not raw request text.',
    exZh: 'deed_id=deed_20260306_ab12cd',
    exEn: 'deed_id=deed_20260306_ab12cd',
  },
  {
    term: 'deed_id',
    type: 'identifier',
    zh: 'Deed 的全局唯一 ID，用于查询、取消、重试、评价和追踪。',
    en: 'Global unique ID of a deed for query, cancel, retry, feedback, and tracing.',
    exZh: 'GET /deeds/{deed_id}',
    exEn: 'GET /deeds/{deed_id}',
  },
  {
    term: 'deed_type',
    type: 'template-key',
    zh: '执行模板键。用于匹配 Lore recipe 和质量规则，不代表语义聚类本身。',
    en: 'Execution-template key. Used to match Lore recipes and quality rules, not semantic clustering itself.',
    exZh: 'research_report / daily_brief\ndeed_type = recipe 查找键',
    exEn: 'research_report / daily_brief\ndeed_type = recipe lookup key',
  },
  {
    term: 'work_scale',
    type: 'execution-shape',
    zh: '执行规模形态。当前统一为 errand / charge / endeavor。',
    en: 'Execution scale shape. Current values: errand / charge / endeavor.',
    exZh: 'plan.work_scale = "charge"',
    exEn: 'plan.work_scale = "charge"',
  },
  {
    term: 'Errand',
    type: 'scale',
    zh: '一次性快速执行，步骤短、反馈快、上下文负载低。',
    en: 'Single-shot fast execution with short steps, quick feedback, and low context load.',
    exZh: '快速摘要 / 简单问答',
    exEn: 'quick summary / simple Q&A',
  },
  {
    term: 'Charge',
    type: 'scale',
    zh: '多步骤但仍是单次闭环交付。可包含 arbiter / rework。',
    en: 'Multi-step single closed-loop delivery. May include arbiter / rework.',
    exZh: '标准报告生成',
    exEn: 'standard report generation',
  },
  {
    term: 'Endeavor',
    type: 'scale',
    zh: '多段落长程执行，包含阶段确认、段落反馈、暂停/恢复。',
    en: 'Long-horizon multi-passage execution with phase confirmation, passage feedback, pause/resume.',
    exZh: '分阶段研究项目',
    exEn: 'phased research program',
  },
  {
    term: 'Norm',
    type: 'governance',
    zh: '系统运行基准（quality/preference/ration）。约束运行边界。',
    en: 'System runtime baseline (quality/preference/ration). Constrains runtime boundaries.',
    exZh: 'Console: Norm',
    exEn: 'Console: Norm',
  },
  {
    term: 'endeavor_phase',
    type: 'endeavor-lifecycle',
    zh: 'Endeavor 当前执行阶段字段。',
    en: 'Current execution-stage field for Endeavor.',
    exZh: 'endeavor_phase',
    exEn: 'endeavor_phase',
  },
  {
    term: 'deed_status',
    type: 'runtime-state',
    zh: 'Deed 的运行状态字段（running/completed/failed/cancelled 等）。',
    en: 'Runtime state field for Deed (running/completed/failed/cancelled, etc.).',
    exZh: 'deed.deed_status = completed',
    exEn: 'deed.deed_status = completed',
  },
  {
    term: 'endeavor_status',
    type: 'endeavor-lifecycle',
    zh: 'Endeavor 生命周期状态字段（running/paused/completed/cancelled/failed）。',
    en: 'Endeavor lifecycle status field (running/paused/completed/cancelled/failed).',
    exZh: 'manifest.endeavor_status = paused',
    exEn: 'manifest.endeavor_status = paused',
  },
  {
    term: 'passage_status',
    type: 'endeavor-lifecycle',
    zh: 'Endeavor 段落结果状态（pending/passed/failed/skipped）。',
    en: 'Endeavor passage result status (pending/passed/failed/skipped).',
    exZh: 'endeavor_passage_recorded.passage_status = passed',
    exEn: 'endeavor_passage_recorded.passage_status = passed',
  },
  {
    term: 'recipe',
    type: 'lore',
    zh: 'Lore 中可评估的执行模板对象。',
    en: 'Evaluable execution-template object in Lore.',
    exZh: 'Lore method_id（内部字段）',
    exEn: 'Lore method_id (internal field)',
  },
  {
    term: 'Weave',
    type: 'counsel-core',
    zh: 'Counsel 将语义意图动态编织为可执行 DAG 的核心机制。',
    en: 'Core Counsel mechanism that dynamically weaves semantic intent into an executable DAG.',
    exZh: 'Counsel Weave',
    exEn: 'Counsel Weave',
  },
  {
    term: 'Weave Plan',
    type: 'counsel-output',
    zh: 'Counsel 产出的具体执行图实例，供 Temporal 消费执行。',
    en: 'Concrete execution-graph instance produced by Counsel and consumed by Temporal.',
    exZh: 'Weave Plan for deed_id',
    exEn: 'Weave Plan for deed_id',
  },
  {
    term: 'skill_type',
    type: 'skill-governance',
    zh: 'Skill 分类字段：capability（能力增强）/ preference（偏好编码）。Skills Endeavor 前必须在 SKILL.md 声明。',
    en: 'Skill classification field: capability / preference. It must be declared in each SKILL.md before Skills Endeavor.',
    exZh: 'skill_type: capability',
    exEn: 'skill_type: capability',
  },
  {
    term: 'provider_route',
    type: 'model-routing',
    zh: '模型提供方回退路径。',
    en: 'Provider fallback path for model routing.',
    exZh: 'model_policy.provider_route',
    exEn: 'model_policy.provider_route',
  },
  {
    term: 'Skill',
    type: 'agent-capability',
    zh: 'Agent 可演进能力单元，以 SKILL.md 为权威来源。',
    en: 'Evolvable agent capability unit, with SKILL.md as the source of truth.',
    exZh: 'workspace/<agent>/skills/*/SKILL.md',
    exEn: 'workspace/<agent>/skills/*/SKILL.md',
  },
  {
    term: 'Ward',
    type: 'admission-control',
    zh: '系统接单闸门：GREEN 接单，YELLOW 降级，RED 暂停新提交。',
    en: 'Admission ward: GREEN accepts, YELLOW degrades, RED blocks new submissions.',
    exZh: 'state/ward.json',
    exEn: 'state/ward.json',
  },
  {
    term: 'Spine',
    type: 'ops-core',
    zh: '治理与学习例程集合（record/witness/learn/judge/relay/tend 等）。',
    en: 'Governance and learning routine set (record/witness/learn/judge/relay/tend, etc.).',
    exZh: 'spine_canon.json',
    exEn: 'spine_canon.json',
  },
  {
    term: 'Psyche',
    type: 'knowledge-core',
    zh: '知识与经验数据层：Memory/Lore/Instinct。',
    en: 'Knowledge and experience data layer: Memory/Lore/Instinct.',
    exZh: 'memory.db / lore.db / instinct.db',
    exEn: 'memory.db / lore.db / instinct.db',
  },
  {
    term: 'Offering',
    type: 'herald',
    zh: 'Deed 交付产物与索引记录，含 delivered_utc 与路径映射。',
    en: 'Delivered artifacts and indexed records of a deed, including delivered_utc and path mapping.',
    exZh: 'state/herald_log.jsonl',
    exEn: 'state/herald_log.jsonl',
  },
];

function _lexiconEsc(v) {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function loadLexicon() {
  const tbody = document.getElementById('lexicon-tbody');
  if (!tbody) return;
  const q = String(document.getElementById('lexicon-q')?.value || '').trim().toLowerCase();
  const zh = (typeof cLang !== 'undefined' ? cLang : 'zh') === 'zh';

  const rows = (LEXICON_ROWS || []).filter((row) => {
    if (!q) return true;
    const hay = [
      row.term,
      row.type,
      row.zh,
      row.en,
      row.exZh,
      row.exEn,
    ].map((x) => String(x || '').toLowerCase()).join(' ');
    return hay.includes(q);
  });

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">${tx('没有匹配词条', 'No matching term')}</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td><code>${_lexiconEsc(row.term)}</code></td>
      <td><span class="badge deterministic">${_lexiconEsc(row.type)}</span></td>
      <td>${_lexiconEsc(zh ? row.zh : row.en)}</td>
      <td><code>${_lexiconEsc(zh ? row.exZh : row.exEn)}</code></td>
    </tr>
  `).join('');
}
