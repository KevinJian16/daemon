const LEXICON_ROWS = [
  {
    term: 'run',
    type: 'execution',
    zh: '一次可追踪的执行实例。系统状态、评价、产物都挂在 run 上，不挂在需求文本上。',
    en: 'A traceable execution instance. State, feedback, and outcomes are bound to run, not raw request text.',
    exZh: 'run_id=run_20260306_ab12cd',
    exEn: 'run_id=run_20260306_ab12cd',
  },
  {
    term: 'run_id',
    type: 'identifier',
    zh: 'run 的全局唯一 ID，用于查询、取消、重试、评价和追踪。',
    en: 'Global unique ID of a run for query, cancel, retry, feedback, and tracing.',
    exZh: 'GET /runs/{run_id}',
    exEn: 'GET /runs/{run_id}',
  },
  {
    term: 'run_type',
    type: 'template-key',
    zh: '执行模板键。用于匹配 Playbook recipe 和质量规则，不代表语义聚类本身。',
    en: 'Execution-template key. Used to match Playbook recipes and quality rules, not semantic clustering itself.',
    exZh: 'research_report / daily_brief\nrun_type = recipe 查找键',
    exEn: 'research_report / daily_brief\nrun_type = recipe lookup key',
  },
  {
    term: 'work_scale',
    type: 'execution-shape',
    zh: '执行规模形态。当前统一为 pulse / thread / campaign。',
    en: 'Execution scale shape. Current values: pulse / thread / campaign.',
    exZh: 'plan.work_scale = "thread"',
    exEn: 'plan.work_scale = "thread"',
  },
  {
    term: 'Pulse',
    type: 'scale',
    zh: '一次性快速执行，步骤短、反馈快、上下文负载低。',
    en: 'Single-shot fast execution with short steps, quick feedback, and low context load.',
    exZh: '快速摘要 / 简单问答',
    exEn: 'quick summary / simple Q&A',
  },
  {
    term: 'Thread',
    type: 'scale',
    zh: '多步骤但仍是单次闭环交付。可包含 review / rework。',
    en: 'Multi-step single closed-loop delivery. May include review / rework.',
    exZh: '标准报告生成',
    exEn: 'standard report generation',
  },
  {
    term: 'Campaign',
    type: 'scale',
    zh: '多里程碑长程执行，包含阶段确认、里程碑反馈、暂停/恢复。',
    en: 'Long-horizon multi-milestone execution with phase confirmation, milestone feedback, pause/resume.',
    exZh: '分阶段研究项目',
    exEn: 'phased research program',
  },
  {
    term: 'Circuit',
    type: 'orchestration',
    zh: '周期触发配置。负责按 cron 自动发起新的 run。',
    en: 'Recurring trigger configuration. It auto-submits new runs by cron.',
    exZh: 'POST /circuits',
    exEn: 'POST /circuits',
  },
  {
    term: 'semantic_spec',
    type: 'semantic',
    zh: '主动提供的语义规格。精确声明 objective/cluster/risk 等语义约束。',
    en: 'Actively provided semantic specification. It explicitly declares objective/cluster/risk and related semantic constraints.',
    exZh: 'submit payload.semantic_spec',
    exEn: 'submit payload.semantic_spec',
  },
  {
    term: 'intent_contract',
    type: 'semantic',
    zh: '意图契约输入。由 objective + constraints + acceptance 组成，交给语义层解析。',
    en: 'Intent-contract input. Built from objective + constraints + acceptance and resolved by semantic layer.',
    exZh: 'submit payload.intent_contract',
    exEn: 'submit payload.intent_contract',
  },
  {
    term: 'cluster_id',
    type: 'semantic',
    zh: '语义聚类 ID。用于 Strategy 分流、统计与治理，不等于 run_type。',
    en: 'Semantic cluster ID used for strategy routing, analytics, and governance; not the same as run_type.',
    exZh: 'clst_research_report',
    exEn: 'clst_research_report',
  },
  {
    term: 'Strategy',
    type: 'governance',
    zh: '语义簇级执行策略实体，包含 strategy_stage 生命周期（candidate/shadow/challenger/champion/retired）。',
    en: 'Cluster-level execution strategy entity with strategy_stage lifecycle (candidate/shadow/challenger/champion/retired).',
    exZh: 'Console: Strategy 发布',
    exEn: 'Console: Strategy panel',
  },
  {
    term: 'Norm',
    type: 'governance',
    zh: '系统运行基准（quality/preference/budget）。约束运行边界，不承载策略晋升逻辑。',
    en: 'System runtime baseline (quality/preference/budget). It constrains runtime boundaries and does not carry strategy promotion logic.',
    exZh: 'Console: Norm',
    exEn: 'Console: Norm',
  },
  {
    term: 'strategy_stage',
    type: 'strategy-lifecycle',
    zh: 'Strategy 生命周期阶段字段。对外统一使用 strategy_stage，避免与其他领域 phase 混淆。',
    en: 'Lifecycle stage field for Strategy. Externally standardized as strategy_stage to avoid phase ambiguity.',
    exZh: 'shadow / challenger / champion',
    exEn: 'shadow / challenger / champion',
  },
  {
    term: 'prev_strategy_stage',
    type: 'strategy-transition',
    zh: 'Strategy 迁移事件中的上一阶段字段。',
    en: 'Previous stage field in Strategy transition events.',
    exZh: 'rollback: prev_strategy_stage=challenger',
    exEn: 'rollback: prev_strategy_stage=challenger',
  },
  {
    term: 'next_strategy_stage',
    type: 'strategy-transition',
    zh: 'Strategy 迁移事件中的目标阶段字段。',
    en: 'Target stage field in Strategy transition events.',
    exZh: 'promote: next_strategy_stage=champion',
    exEn: 'promote: next_strategy_stage=champion',
  },
  {
    term: 'campaign_phase',
    type: 'campaign-lifecycle',
    zh: 'Campaign 当前执行阶段字段（与 Strategy 的 strategy_stage 不同层级）。',
    en: 'Current execution-stage field for Campaign (different layer from Strategy strategy_stage).',
    exZh: 'campaign_phase',
    exEn: 'campaign_phase',
  },
  {
    term: 'run_status',
    type: 'runtime-state',
    zh: 'Run 的运行状态字段（running/completed/failed/cancelled 等）。',
    en: 'Runtime state field for Run (running/completed/failed/cancelled, etc.).',
    exZh: 'run.run_status = completed',
    exEn: 'run.run_status = completed',
  },
  {
    term: 'campaign_status',
    type: 'campaign-lifecycle',
    zh: 'Campaign 生命周期状态字段（running/paused/completed/cancelled/failed）。',
    en: 'Campaign lifecycle status field (running/paused/completed/cancelled/failed).',
    exZh: 'manifest.campaign_status = paused',
    exEn: 'manifest.campaign_status = paused',
  },
  {
    term: 'milestone_status',
    type: 'campaign-lifecycle',
    zh: 'Campaign 里程碑结果状态（pending/passed/failed/skipped）。',
    en: 'Campaign milestone result status (pending/passed/failed/skipped).',
    exZh: 'campaign_milestone_recorded.milestone_status = passed',
    exEn: 'campaign_milestone_recorded.milestone_status = passed',
  },
  {
    term: 'recipe',
    type: 'playbook',
    zh: 'Playbook 中可评估的执行模板对象。',
    en: 'Evaluable execution-template object in Playbook.',
    exZh: 'Playbook method_id（内部字段）',
    exEn: 'Playbook method_id (internal field)',
  },
  {
    term: 'Weave',
    type: 'router-core',
    zh: 'Router 将语义意图动态编织为可执行 DAG 的核心机制。',
    en: 'Core Router mechanism that dynamically weaves semantic intent into an executable DAG.',
    exZh: 'Router Weave',
    exEn: 'Router Weave',
  },
  {
    term: 'Weave Plan',
    type: 'router-output',
    zh: 'Router 产出的具体执行图实例，供 Temporal 消费执行。',
    en: 'Concrete execution-graph instance produced by Router and consumed by Temporal.',
    exZh: 'Weave Plan for run_id',
    exEn: 'Weave Plan for run_id',
  },
  {
    term: 'skill_type',
    type: 'skill-governance',
    zh: 'Skill 分类字段：capability（能力增强）/ preference（偏好编码）。Skills Campaign 前必须在 SKILL.md 声明。',
    en: 'Skill classification field: capability / preference. It must be declared in each SKILL.md before Skills Campaign.',
    exZh: 'skill_type: capability',
    exEn: 'skill_type: capability',
  },
  {
    term: 'provider_route',
    type: 'model-routing',
    zh: '模型提供方回退路径，避免和 Circuit 概念混淆。',
    en: 'Provider fallback path for model routing, kept distinct from Circuit concepts.',
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
    term: 'Gate',
    type: 'admission-control',
    zh: '系统接单闸门：GREEN 接单，YELLOW 降级，RED 暂停新提交。',
    en: 'Admission gate: GREEN accepts, YELLOW degrades, RED blocks new submissions.',
    exZh: 'state/gate.json',
    exEn: 'state/gate.json',
  },
  {
    term: 'Spine',
    type: 'ops-core',
    zh: '治理与学习例程集合（record/witness/learn/judge/relay/tend 等）。',
    en: 'Governance and learning routine set (record/witness/learn/judge/relay/tend, etc.).',
    exZh: 'spine_registry.json',
    exEn: 'spine_registry.json',
  },
  {
    term: 'Fabric',
    type: 'knowledge-core',
    zh: '知识与经验数据层：Memory/Playbook/Compass。',
    en: 'Knowledge and experience data layer: Memory/Playbook/Compass.',
    exZh: 'memory.db / playbook.db / compass.db',
    exEn: 'memory.db / playbook.db / compass.db',
  },
  {
    term: 'Outcome',
    type: 'delivery',
    zh: 'run 交付产物与索引记录，含 delivered_utc 与路径映射。',
    en: 'Delivered artifacts and indexed records of a run, including delivered_utc and path mapping.',
    exZh: 'outcome/index.json',
    exEn: 'outcome/index.json',
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
