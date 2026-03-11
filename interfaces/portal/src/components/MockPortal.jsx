import {
  ArrowDown,
  ArrowUp,
  Check,
  Clock3,
  Ellipsis,
  Folder,
  FolderOpen,
  Layers3,
  LibraryBig,
  Play,
  Search,
  Sparkles,
  SquarePen,
  TimerReset,
  Waypoints,
} from "lucide-react";
import { startTransition, useDeferredValue, useEffect, useState } from "react";
import ConversationDock from "./ConversationDock";
import { cx, deedStatusLabel, deedStatusTone, formatDateTime, shortText } from "../lib/format";

const CADENCE_OPTIONS = [
  "每周三 09:30 复查一次",
  "每周五 16:00 回桌一次",
  "每两周周一 10:15 回桌一次",
];

const ATTACHMENT_OPTIONS = [
  "taskgroup-demo.py",
  "exception-group-notes.md",
  "runtime-crash-log.txt",
];

const INITIAL_FOLIOS = [
  {
    id: "folio_runtime",
    title: "Runtime / Python",
    summary: "异常、取消、并发语义",
    note: "收敛 Python 运行时故障和并发语义的卷宗。",
    writCount: 2,
    slipIds: ["slip_taskgroup", "slip_gather", "slip_cancel"],
  },
  {
    id: "folio_portal",
    title: "Portal Interaction",
    summary: "Apple 式对象动作检查",
    note: "只用来检查 Portal 里的对象进入、比较和冻结手感。",
    writCount: 1,
    slipIds: ["slip_portal"],
  },
];

const INITIAL_SLIPS = [
  {
    id: "slip_taskgroup",
    title: "TaskGroup 异常处理技术札",
    summary: "整理多子任务失败、取消传播和 ExceptionGroup 收束行为",
    objective:
      "整理 Python 3.11 `asyncio.TaskGroup` 在多子任务失败、取消传播和 `ExceptionGroup` 收束上的真实行为，写成一份工程师可以直接拿来判断故障现场的技术说明。",
    stance: "在场",
    updatedAt: "2026-03-11T09:42:00Z",
    folioId: "folio_runtime",
    cadence: {
      enabled: true,
      schedule: "每周三 09:30 复查一次",
    },
    structure: [
      "先只讲 TaskGroup 在“首个子任务抛错”时的控制流，不混进 gather。",
      "把取消传播拆成父协程、兄弟子任务、退出阶段三个观察面。",
      "单独讲 ExceptionGroup 里为什么会出现多错误收束，而不是被第一个异常截断。",
      "最后附上一段对照代码和一张表，告诉读者什么时候该用 TaskGroup，什么时候该退回 gather。",
    ],
    deed: {
      id: "deed_mock_20260311_01",
      status: "settling",
      createdAt: "2026-03-11T08:08:00Z",
      updatedAt: "2026-03-11T09:42:00Z",
      feedback: "待确认",
      selectedVersionId: "v2",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "偏教材体，解释完整但太长。",
          excerpt:
            "版本 A 先把 TaskGroup 的契约铺满，再顺着 `__aexit__` 讲退出收束。这版完整，但现场查询时会显得偏慢。",
          winning: false,
        },
        {
          id: "v2",
          name: "版本 B",
          note: "结构最稳，表格和代码示例更适合工程现场。",
          excerpt:
            "版本 B 把问题收束成“谁先失败、谁被取消、异常最后怎样聚合”三步，读者进入故障现场时更容易拿来直接对照。",
          winning: true,
        },
        {
          id: "v3",
          name: "版本 C",
          note: "语气更硬，但异常收束部分太跳。",
          excerpt:
            "版本 C 更强调“结构化并发不是结果聚合”，但它跳过了 `ExceptionGroup` 的落点，所以比较时会让人感觉断层。",
          winning: false,
        },
      ],
      files: [
        {
          id: "file_taskgroup_main",
          name: "taskgroup-exception-behavior.md",
          content:
            "## TaskGroup 的异常收束\n\n当任一子任务抛错，组会进入退出期；其余仍存活的兄弟任务会被取消，随后所有在退出期观察到的异常被收束进 `ExceptionGroup`。",
        },
        {
          id: "file_taskgroup_table",
          name: "taskgroup-vs-gather-table.md",
          content:
            "## TaskGroup vs gather\n\n- `TaskGroup`: 以结构化退出为中心。\n- `gather`: 以结果聚合为中心。\n- 当你需要组级失败语义时，应优先考虑 `TaskGroup`。",
        },
        {
          id: "file_taskgroup_demo",
          name: "taskgroup-cancellation-demo.py",
          content:
            "import asyncio\n\nasync def boom():\n    raise RuntimeError('boom')\n\nasync def main():\n    async with asyncio.TaskGroup() as tg:\n        tg.create_task(boom())\n        tg.create_task(asyncio.sleep(10))",
        },
      ],
    },
    messages: [
      {
        message_id: "msg_1",
        role: "assistant",
        content:
          "我先把这张札收束成一条清晰主线：`TaskGroup` 不是“并发版 gather”，它的核心是**结构化收束**。只要有一个子任务失败，组就会进入退出阶段，并把相关异常一起收起来。",
        created_utc: "2026-03-11T08:10:00Z",
      },
      {
        message_id: "msg_2",
        role: "user",
        content: "重点把“兄弟任务为什么会被一起取消”讲清楚，别停留在概念。",
        created_utc: "2026-03-11T08:14:00Z",
      },
      {
        message_id: "msg_3",
        role: "assistant",
        content:
          "可以。现在版本 B 的讲法是：\n\n1. 某个子任务先抛错。\n2. `TaskGroup.__aexit__` 进入收束。\n3. 其余仍存活的兄弟任务被取消。\n4. 组等待它们停下。\n5. 最后把这轮退出期观察到的异常一起打包进 `ExceptionGroup`。",
        created_utc: "2026-03-11T08:29:00Z",
      },
      {
        message_id: "msg_4",
        role: "user",
        content: "再给我一段和 `gather(return_exceptions=False)` 的对照，不然用户会混。",
        created_utc: "2026-03-11T08:37:00Z",
      },
      {
        message_id: "msg_5",
        role: "assistant",
        content:
          "已经补了。对照表现在明确写成：\n\n| 场景 | `TaskGroup` | `gather(...)` |\n| --- | --- | --- |\n| 某子任务抛错 | 进入结构化退出，取消兄弟任务并收束异常 | 默认把第一个异常抛给调用方 |\n| 异常形态 | `ExceptionGroup` | 单异常或调用方自行处理 |",
        created_utc: "2026-03-11T09:18:00Z",
      },
      {
        message_id: "msg_6",
        role: "assistant",
        content: "这轮 deed 已进入 `settling`。现在可以比较候选版本、改选保留版本，然后再冻结正式结果。",
        created_utc: "2026-03-11T09:42:00Z",
      },
    ],
  },
  {
    id: "slip_gather",
    title: "gather vs TaskGroup",
    summary: "补一张对照札，单看错误传播模型",
    objective:
      "把 `gather(return_exceptions=False)` 和 `TaskGroup` 在错误传播上的差异压成一页短札，便于遇到并发报错时快速判断。",
    stance: "在场",
    updatedAt: "2026-03-11T07:11:00Z",
    folioId: "folio_runtime",
    cadence: {
      enabled: false,
      schedule: "每周五 16:00 回桌一次",
    },
    structure: [
      "先给一张总表，明确两者心智模型不同。",
      "再给一段失败时序，回答“错误先到哪里”。",
      "最后收成一条工程建议：什么时候优先结构化并发。",
    ],
    deed: {
      id: "deed_mock_20260311_02",
      status: "running",
      createdAt: "2026-03-11T06:58:00Z",
      updatedAt: "2026-03-11T07:11:00Z",
      feedback: "执行中",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "正在行事中，主线已成。",
          excerpt: "当前正在生成对照表，还没有到最终 settle 阶段。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_gather_outline",
          name: "gather-compare-outline.md",
          content: "## 对照札草稿\n\n- 错误传播\n- 兄弟任务命运\n- 调用方观察到的异常形态",
        },
      ],
    },
    messages: [
      {
        message_id: "msg_g1",
        role: "assistant",
        content: "我先把 `gather` 和 `TaskGroup` 的差别收成一页：一个是聚合结果，一个是结构化退出。",
        created_utc: "2026-03-11T06:58:00Z",
      },
      {
        message_id: "msg_g2",
        role: "user",
        content: "尽量别把这一页写成教程，像现场排障卡片。",
        created_utc: "2026-03-11T07:01:00Z",
      },
      {
        message_id: "msg_g3",
        role: "assistant",
        content: "收到。我会把正文压短，把判断句放前面。",
        created_utc: "2026-03-11T07:11:00Z",
      },
    ],
  },
  {
    id: "slip_cancel",
    title: "Cancellation Notes",
    summary: "把取消链路独立成一张短札",
    objective: "拆出一张只讲取消传播的短札，避免在主文里混淆焦点。",
    stance: "归档",
    updatedAt: "2026-03-10T14:24:00Z",
    folioId: "folio_runtime",
    cadence: {
      enabled: false,
      schedule: "每两周周一 10:15 回桌一次",
    },
    structure: [
      "取消来自哪里。",
      "取消如何向兄弟任务扩散。",
      "取消和失败一起出现时谁先被看到。",
    ],
    deed: {
      id: "deed_mock_20260310_03",
      status: "closed",
      createdAt: "2026-03-10T12:10:00Z",
      updatedAt: "2026-03-10T14:24:00Z",
      feedback: "已冻结",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "已冻结成短札。",
          excerpt: "这张短札只保留取消传播链路，供主札外链。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_cancel_notes",
          name: "cancellation-notes.md",
          content: "## Cancellation Notes\n\n这是一张已冻结短札，只保留取消传播的核心链路。",
        },
      ],
    },
    messages: [
      {
        message_id: "msg_c1",
        role: "assistant",
        content: "这张短札已经冻结，不再继续扩写。",
        created_utc: "2026-03-10T14:24:00Z",
      },
    ],
  },
  {
    id: "slip_portal",
    title: "Portal 动态检查",
    summary: "检查对象进入、比较、冻结的前台手感",
    objective: "做一张专门检查 Portal 动态和比较模式的假札，只看前台感受，不挂真实后端。",
    stance: "在场",
    updatedAt: "2026-03-11T05:12:00Z",
    folioId: "folio_portal",
    cadence: {
      enabled: true,
      schedule: "每周五 16:00 回桌一次",
    },
    structure: [
      "确认对象头部进入感和动作密度。",
      "确认 deed compare 的切换语法。",
      "确认冻结后结果文件的收束方式。",
    ],
    deed: {
      id: "deed_mock_20260311_04",
      status: "settling",
      createdAt: "2026-03-11T04:20:00Z",
      updatedAt: "2026-03-11T05:12:00Z",
      feedback: "待比较",
      selectedVersionId: "v2",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "页面稳定，但太像管理后台。",
          excerpt: "这版组织清楚，但壳体过硬，不像 Claude 的主区。",
          winning: false,
        },
        {
          id: "v2",
          name: "版本 B",
          note: "更接近 Claude 壳，但按钮尺度还要继续压。",
          excerpt: "这版更接近目标方向，剩下主要是字级和间距要继续收。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_portal_motion",
          name: "portal-motion-checklist.md",
          content: "## Portal Motion Checklist\n\n- 进入\n- 比较\n- 冻结\n- 结果文件收束",
        },
      ],
    },
    messages: [
      {
        message_id: "msg_p1",
        role: "assistant",
        content: "这张是假札，专门看 Portal 前端动作，不拉真实任务数据。",
        created_utc: "2026-03-11T04:20:00Z",
      },
    ],
  },
  {
    id: "slip_loose",
    title: "Async Runtime Filing",
    summary: "等这轮 deed 定稿后并回卷宗",
    objective: "准备把运行时相关散札归并回卷宗，先留在桌面上整理引用关系。",
    stance: "卷外",
    updatedAt: "2026-03-11T03:35:00Z",
    folioId: "",
    cadence: {
      enabled: false,
      schedule: "每周三 09:30 复查一次",
    },
    structure: [
      "整理外链到哪些已冻结札。",
      "标记哪些内容应并回 Runtime / Python 卷。",
    ],
    deed: {
      id: "deed_mock_20260311_05",
      status: "closed",
      createdAt: "2026-03-11T02:48:00Z",
      updatedAt: "2026-03-11T03:35:00Z",
      feedback: "归并前待确认",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "只是待并卷记录。",
          excerpt: "这张札不再扩写，等卷内结构定稳后并回。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_loose_plan",
          name: "runtime-filing-plan.md",
          content: "## Filing Plan\n\n这是一张卷外假札，用来检查并卷入口和动作反馈。",
        },
      ],
    },
    messages: [
      {
        message_id: "msg_l1",
        role: "assistant",
        content: "这张札留在卷外，等你确认后再并回卷宗。",
        created_utc: "2026-03-11T03:35:00Z",
      },
    ],
  },
];

const INITIAL_DRAFTS = [
  {
    id: "draft_async_faults",
    title: "Async 故障路径整理",
    summary: "把 async runtime 里的几类故障表象收成一张能成札的对象。",
    convergence: "目标已收窄，方案待定稿",
    currentScheme:
      "当前倾向成一张 `Slip`，主题限定在“`TaskGroup` 失败后，调用者实际观察到什么”，避免把取消、重试、日志系统全挤进来。",
    priorDesigns: [
      "旧方案 A：做成“并发错误百科”，过大。",
      "旧方案 B：做成 `Folio` 起卷草案，暂时过重。",
    ],
    materials: ["incident-notes.md", "python-311-doc-links.md"],
    targetFolioId: "folio_runtime",
    messages: [
      {
        message_id: "msg_d1",
        role: "assistant",
        content: "这还是一张 `Draft`。现在要做的是收窄边界，而不是急着起一轮 `Deed`。",
        created_utc: "2026-03-11T08:52:00Z",
      },
      {
        message_id: "msg_d2",
        role: "user",
        content: "先不要谈日志系统，只收 `TaskGroup` 失败后的观察结果。",
        created_utc: "2026-03-11T08:57:00Z",
      },
    ],
  },
];

const INITIAL_DEED_HISTORY = {
  slip_taskgroup: [
    {
      id: "deed_mock_20260310_12",
      status: "closed",
      createdAt: "2026-03-10T08:15:00Z",
      updatedAt: "2026-03-10T09:02:00Z",
      feedback: "已冻结",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "冻结稿 A",
          note: "第一次收束的短版。",
          excerpt: "先把 TaskGroup 失败后的观察顺序压成一页短札。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_taskgroup_archive_a",
          name: "taskgroup-short-note.md",
          content: "## TaskGroup Short Note\n\n这是较早的一轮冻结结果，只保留短版观察顺序。",
        },
      ],
    },
    {
      id: "deed_mock_20260309_07",
      status: "closed",
      createdAt: "2026-03-09T06:40:00Z",
      updatedAt: "2026-03-09T07:18:00Z",
      feedback: "已冻结",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "冻结稿 B",
          note: "更早的一轮铺底稿。",
          excerpt: "这轮还偏教程体，只保留一份旧产物供回看。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_taskgroup_archive_b",
          name: "taskgroup-archive-draft.md",
          content: "## Archived Draft\n\n这是更早的一轮 deed 产物，用来检查页面里的淡出效果。",
        },
      ],
    },
  ],
  slip_portal: [
    {
      id: "deed_mock_20260310_portal",
      status: "closed",
      createdAt: "2026-03-10T02:10:00Z",
      updatedAt: "2026-03-10T03:02:00Z",
      feedback: "已冻结",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "冻结稿 A",
          note: "先前的 Portal 动线假稿。",
          excerpt: "保留对象进入和返回的旧检查稿。",
          winning: true,
        },
      ],
      files: [
        {
          id: "file_portal_archive",
          name: "portal-archive-note.md",
          content: "## Portal Archive\n\n这是一轮已经淡出的旧 deed。",
        },
      ],
    },
  ],
};

const INITIAL_DEED_THREADS = Object.fromEntries(
  [
    ...INITIAL_SLIPS.map((slip) => slip.deed),
    ...Object.values(INITIAL_DEED_HISTORY).flat(),
  ].map((deed) => [
    deed.id,
    [
      {
        message_id: `${deed.id}_thread_1`,
        role: "assistant",
        content:
          deed.status === "running"
            ? "这一轮还在推进，补记会继续进入当前 deed。"
            : deed.status === "settling"
              ? "这一轮停在比较阶段，主要看候选和保留。"
              : "这一轮已经收束，只保留产物标签和对话历史。",
        created_utc: deed.updatedAt,
      },
    ],
  ]),
);

const FOLIO_CONTENT = {
  folio_runtime: {
    messages: [
      {
        message_id: "msg_fr1",
        role: "assistant",
        content: "这卷现在主要在整理 `TaskGroup`、`gather` 和取消传播三张札之间的关系，先不要再扩进新的并发主题。",
        created_utc: "2026-03-11T08:24:00Z",
      },
      {
        message_id: "msg_fr2",
        role: "user",
        content: "先把 `TaskGroup` 放在卷的中心位置，另外两张只作为支撑和对照。",
        created_utc: "2026-03-11T08:31:00Z",
      },
    ],
  },
  folio_portal: {
    messages: [
      {
        message_id: "msg_fp1",
        role: "assistant",
        content: "这卷只用来检查 Portal 的前台语法，不把后端机制和真实任务装进来。",
        created_utc: "2026-03-11T04:32:00Z",
      },
    ],
  },
};

const INITIAL_FOLIO_EDGES = {
  folio_runtime: [
    ["slip_cancel", "slip_taskgroup"],
    ["slip_taskgroup", "slip_gather"],
  ],
  folio_portal: [],
};

const INITIAL_FOLIO_FOCUS = {
  folio_runtime: "slip_taskgroup",
  folio_portal: "slip_portal",
};

function makeId(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function versionName(index) {
  return `版本 ${String.fromCharCode(65 + index)}`;
}

function canonicalEdge(fromId, toId) {
  return [fromId, toId].sort();
}

function deedArtifactLabel(deed) {
  return deed.files[0]?.name || deed.versions.find((item) => item.winning)?.name || deed.versions[0]?.name || "无产物";
}

function deedAgeOpacityClass(updatedAt) {
  const ageHours = (Date.now() - new Date(updatedAt).getTime()) / 36e5;
  if (ageHours > 48) return "opacity-45";
  if (ageHours > 24) return "opacity-65";
  return "opacity-100";
}

function slipStatusDot(status) {
  if (status === "running") return "bg-[#4B7BEC]";
  if (status === "settling") return "bg-[#C46A2F]";
  return "bg-[#5D8A63]";
}

function moveLabel(text, index) {
  const clean = String(text || "").replace(/^[0-9.\s-]+/, "").trim();
  return shortText(clean || `Move ${index + 1}`, 28);
}

function buildMoveGraph(structure) {
  const labels = (structure.length ? structure : ["定义对象", "整理边界", "准备执行"]).map((item, index) => ({
    id: `move_${index}`,
    title: moveLabel(item, index),
    detail: String(item || "").trim(),
  }));

  if (labels.length === 1) {
    return {
      width: 720,
      height: 220,
      nodes: [{ ...labels[0], x: 280, y: 72 }],
      edges: [],
    };
  }

  if (labels.length === 2) {
    return {
      width: 760,
      height: 220,
      nodes: [
        { ...labels[0], x: 120, y: 72 },
        { ...labels[1], x: 420, y: 72 },
      ],
      edges: [[0, 1]],
    };
  }

  const nodes = [];
  const edges = [];

  nodes.push({ ...labels[0], x: 70, y: 96 });
  if (labels[1]) nodes.push({ ...labels[1], x: 280, y: 28 });
  if (labels[2]) nodes.push({ ...labels[2], x: 280, y: 164 });
  if (labels[3]) {
    nodes.push({ ...labels[3], x: 510, y: 96 });
    edges.push([0, 1], [0, 2], [1, 3], [2, 3]);
  } else {
    edges.push([0, 1], [1, 2]);
  }

  let anchorIndex = labels[3] ? 3 : labels.length - 1;
  for (let index = 4; index < labels.length; index += 1) {
    nodes.push({
      ...labels[index],
      x: 510 + (index - 3) * 210,
      y: 96,
    });
    edges.push([anchorIndex, index]);
    anchorIndex = index;
  }

  return {
    width: Math.max(860, 720 + Math.max(0, labels.length - 4) * 210),
    height: 264,
    nodes,
    edges,
  };
}

function moveProgress(deed, count) {
  if (!count) return { activeIndex: -1, visitedMax: -1 };
  if (deed.status === "running") {
    const activeIndex = Math.min(count - 1, Math.max(1, Math.floor(count / 2)));
    return { activeIndex, visitedMax: Math.max(0, activeIndex - 1) };
  }
  return { activeIndex: count - 1, visitedMax: count - 1 };
}

const GRAPH_TOKENS = {
  canvas: "#F5F5F0",
  nodeSurface: "#FCFBF8",
  cardSurface: "#FAF8F5",
  borderDefault: "#ADADAD",
  lineDefault: "#CDCDCD",
  textPrimary: "#292929",
  visitedTone: "#686868",
  activeTone: "#AE5630",
};

const GRAPH_RELIEF = {
  node: "0 1.5px 0 rgba(255,255,255,0.96) inset, 0 -1px 0 rgba(41,41,41,0.06) inset, 0 18px 34px rgba(41,41,41,0.08), 0 6px 12px rgba(41,41,41,0.05)",
  activeNode:
    "0 1.5px 0 rgba(255,255,255,0.28) inset, 0 -1px 0 rgba(120,53,25,0.18) inset, 0 18px 34px rgba(174,86,48,0.24), 0 6px 12px rgba(41,41,41,0.08)",
  card: "0 1.5px 0 rgba(255,255,255,0.92) inset, 0 -1px 0 rgba(41,41,41,0.05) inset, 0 22px 40px rgba(41,41,41,0.08), 0 8px 14px rgba(41,41,41,0.05)",
  folioCard:
    "0 1.5px 0 rgba(255,255,255,0.95) inset, 0 -1px 0 rgba(41,41,41,0.04) inset, 0 26px 46px rgba(41,41,41,0.09), 0 10px 18px rgba(41,41,41,0.05)",
};

function MoveGraphCanvas({ graph, progress = null, compact = false, className = "", mode = "structure", deedStatus = "closed" }) {
  const isDeed = mode === "deed";
  const graphProgress = progress || { activeIndex: -1, visitedMax: -1 };
  const scale = compact ? 0.74 : 1;
  const nodeWidth = compact ? 150 : 182;
  const nodeHeight = compact ? 62 : 74;
  const padding = compact ? 26 : 34;
  const boardWidth = graph.width * scale + padding * 2;
  const boardHeight = graph.height * scale + padding * 2;

  function scaledX(value) {
    return padding + value * scale;
  }

  function scaledY(value) {
    return padding + value * scale;
  }

  return (
    <div
      className={cx(
        "overflow-x-auto rounded-[1.6rem]",
        className,
      )}
      style={{ background: GRAPH_TOKENS.canvas, boxShadow: "inset 0 0 0 1px rgba(41,41,41,0.06)" }}
    >
      <div className="relative" style={{ width: `${boardWidth}px`, height: `${boardHeight}px` }}>
        {!isDeed ? (
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(173,173,173,0.14)_1px,transparent_0)] bg-[length:18px_18px] opacity-[0.08]" />
        ) : null}
        <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${boardWidth} ${boardHeight}`} preserveAspectRatio="none">
          {graph.edges.map(([fromIndex, toIndex]) => {
            const fromNode = graph.nodes[fromIndex];
            const toNode = graph.nodes[toIndex];
            const startX = scaledX(fromNode.x) + nodeWidth / 2;
            const startY = scaledY(fromNode.y) + nodeHeight / 2;
            const endX = scaledX(toNode.x) + nodeWidth / 2;
            const endY = scaledY(toNode.y) + nodeHeight / 2;
            const midX = (startX + endX) / 2;
            const visited = toIndex <= graphProgress.visitedMax || fromIndex < graphProgress.activeIndex;
            const activeEdge =
              isDeed &&
              deedStatus === "running" &&
              fromIndex === Math.max(0, graphProgress.activeIndex - 1) &&
              toIndex === graphProgress.activeIndex;
            const pathDefinition = `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`;

            return (
              <g key={`${fromIndex}-${toIndex}`}>
                <path
                  d={pathDefinition}
                  fill="none"
                  stroke={
                    isDeed
                      ? visited
                        ? GRAPH_TOKENS.visitedTone
                        : "rgba(205,205,205,0.48)"
                      : GRAPH_TOKENS.lineDefault
                  }
                  strokeWidth={compact ? "1.7" : "2"}
                  strokeLinecap="round"
                  opacity={isDeed && !visited && !activeEdge ? 0.48 : 1}
                />
                {activeEdge ? (
                  <path
                    d={pathDefinition}
                    fill="none"
                    stroke={GRAPH_TOKENS.activeTone}
                    strokeWidth={compact ? "2.2" : "2.6"}
                    strokeLinecap="round"
                    strokeDasharray="9 13"
                    className="portal-flow-stroke"
                  />
                ) : null}
              </g>
            );
          })}
        </svg>

        {graph.nodes.map((node, index) => {
          const isVisited = index <= graphProgress.visitedMax;
          const isActive = index === graphProgress.activeIndex;
          const background = isDeed
            ? isActive
              ? `linear-gradient(180deg, rgba(255,255,255,0.24) 0px, rgba(255,255,255,0.08) 14px, rgba(255,255,255,0) 30px), linear-gradient(180deg, rgba(255,255,255,0) 52%, rgba(120,53,25,0.12) 100%), ${GRAPH_TOKENS.activeTone}`
              : `linear-gradient(180deg, rgba(255,255,255,0.82) 0px, rgba(255,255,255,0.3) 14px, rgba(255,255,255,0) 28px), linear-gradient(180deg, rgba(255,255,255,0) 52%, rgba(41,41,41,0.03) 100%), ${GRAPH_TOKENS.nodeSurface}`
            : `linear-gradient(180deg, rgba(255,255,255,0.86) 0px, rgba(255,255,255,0.34) 14px, rgba(255,255,255,0) 28px), linear-gradient(180deg, rgba(255,255,255,0) 54%, rgba(41,41,41,0.03) 100%), ${GRAPH_TOKENS.nodeSurface}`;
          const borderColor = isDeed
            ? isActive
              ? GRAPH_TOKENS.activeTone
              : isVisited
                ? GRAPH_TOKENS.visitedTone
                : GRAPH_TOKENS.borderDefault
            : GRAPH_TOKENS.borderDefault;
          const textColor = isDeed ? (isActive ? "#FFF9F3" : GRAPH_TOKENS.textPrimary) : GRAPH_TOKENS.textPrimary;
          const opacity = isDeed && !isActive && !isVisited ? 0.48 : 1;
          const boxShadow = isDeed && isActive ? GRAPH_RELIEF.activeNode : GRAPH_RELIEF.node;
          return (
            <div
              key={node.id}
              className={cx(
                "absolute border transition duration-150",
                compact ? "rounded-[1.55rem] px-[1rem] py-[1rem]" : "rounded-[1.75rem] px-[1.08rem] py-[1.08rem]",
                isDeed && isActive ? "portal-flow-node" : "",
              )}
              style={{
                left: `${scaledX(node.x)}px`,
                top: `${scaledY(node.y)}px`,
                width: `${nodeWidth}px`,
                minHeight: `${nodeHeight}px`,
                background,
                color: textColor,
                opacity,
                borderColor: isActive ? borderColor : "rgba(173,173,173,0.72)",
                boxShadow,
              }}
            >
              <div className="flex items-start gap-2.5">
                {isDeed ? (
                  <span
                    className={cx(
                      "mt-[0.28rem] inline-flex h-2.5 w-2.5 shrink-0 rounded-full",
                      isActive
                        ? "bg-[#ffd6bf] animate-pulse"
                        : isVisited
                          ? "bg-[#686868]"
                          : "bg-[#ADADAD]",
                    )}
                  />
                ) : (
                  <span
                    className="inline-flex h-[1.46rem] w-[1.46rem] shrink-0 items-center justify-center rounded-full text-[10px] font-medium"
                    style={{
                      background: "rgba(245,245,240,0.94)",
                      color: GRAPH_TOKENS.visitedTone,
                      boxShadow: "inset 0 1px 0 rgba(255,255,255,0.86), 0 2px 4px rgba(41,41,41,0.05)",
                    }}
                  >
                    {index + 1}
                  </span>
                )}
                <div className={cx("line-clamp-2 font-medium leading-[1.14]", compact ? "text-[12.8px]" : "text-[14.2px]")}>
                  {node.title}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SurfaceCard({ children, className = "" }) {
  return (
    <div className={cx("rounded-[1.35rem] border border-[rgba(0,0,0,0.06)] bg-white shadow-claude", className)}>
      {children}
    </div>
  );
}

function SidebarItem({ title, summary, meta, active = false, onClick, icon = null }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "group flex w-full items-start gap-3 rounded-2xl px-3 py-2.5 text-left transition-colors",
        active ? "bg-[#DDD9CE]" : "hover:bg-[#E5E2D8]",
      )}
    >
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-white/80 text-[#807d76]">
        {icon || <div className="h-2 w-2 rounded-full bg-[#c8c2b3]" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13.5px] font-medium leading-5 text-[#1a1a18]">{title}</div>
        <div className="mt-0.5 truncate text-[12px] text-[#6b6a68]">{summary}</div>
        <div className="mt-1 text-[11px] text-[#9a9893]">{meta}</div>
      </div>
      <div className="opacity-0 transition group-hover:opacity-100">
        <Ellipsis width={15} height={15} className="text-[#8d8b84]" />
      </div>
    </button>
  );
}

function MockSidebar({
  drafts,
  folios,
  slips,
  selectedTarget,
  searchQuery,
  onSearchChange,
  onSelectDraft,
  onSelectFolio,
  onSelectSlip,
  onCreateSlip,
  onShuffle,
}) {
  return (
    <aside className="h-full w-[308px] shrink-0 border-r border-[rgba(0,0,0,0.06)] bg-[#ECEBE4]">
      <div className="flex h-full flex-col">
        <div className="border-b border-[rgba(0,0,0,0.05)] px-3 pb-4 pt-4">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Portal</div>
          <div className="mt-1 text-[15px] font-medium text-[#1a1a18]">Daemon</div>

          <div className="mt-4 flex items-center gap-2">
            <button
              type="button"
              onClick={onCreateSlip}
              className="flex h-9 min-w-0 flex-1 items-center justify-center gap-2 rounded-2xl border border-[rgba(0,0,0,0.08)] bg-white/80 px-3 text-sm font-medium text-[#1a1a18] shadow-sm transition hover:bg-white"
            >
              <SquarePen width={16} height={16} />
              <span>新建</span>
            </button>
            <button
              type="button"
              onClick={onShuffle}
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[rgba(0,0,0,0.08)] bg-white/80 text-[#6b6a68] shadow-sm transition hover:bg-white"
              title="随机切换一张假札"
            >
              <Sparkles width={16} height={16} />
            </button>
          </div>

          <label className="mt-4 flex items-center gap-2 rounded-2xl border border-[rgba(0,0,0,0.06)] bg-white/70 px-3 py-2 shadow-sm">
            <Search width={15} height={15} className="text-[#8d8b84]" />
            <input
              value={searchQuery}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Search Portal"
              className="w-full border-none bg-transparent text-sm text-[#1a1a18] outline-none placeholder:text-[#9a9893]"
            />
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-5">
          {drafts.length ? (
            <section className="mt-6">
              <div className="mb-2 px-3 text-[11px] font-medium uppercase tracking-[0.16em] text-[#8d8b84]">案头</div>
              {drafts.map((draft) => (
                <SidebarItem
                  key={draft.id}
                  title={draft.title}
                  summary={draft.summary}
                  meta="尚未成札 · 当前线程"
                  active={selectedTarget.kind === "draft" && selectedTarget.id === draft.id}
                  onClick={() => onSelectDraft(draft.id)}
                />
              ))}
            </section>
          ) : null}

          <section className="mt-6">
            <div className="mb-2 px-3 text-[11px] font-medium uppercase tracking-[0.16em] text-[#8d8b84]">卷宗</div>
            {folios.map((folio) => (
              <SidebarItem
                key={folio.id}
                title={folio.title}
                summary={folio.summary}
                meta={`${folio.slipIds.length} 张签札 · ${folio.writCount} 道成文`}
                active={selectedTarget.kind === "folio" && selectedTarget.id === folio.id}
                onClick={() => onSelectFolio(folio.id)}
                icon={<Folder width={15} height={15} />}
              />
            ))}
          </section>

          <section className="mt-6">
            <div className="mb-2 px-3 text-[11px] font-medium uppercase tracking-[0.16em] text-[#8d8b84]">散札</div>
            {slips.length ? (
              slips.map((slip) => (
                <SidebarItem
                  key={slip.id}
                  title={slip.title}
                  summary={slip.summary}
                  meta={slip.stance}
                  active={selectedTarget.kind === "slip" && selectedTarget.id === slip.id}
                  onClick={() => onSelectSlip(slip.id)}
                />
              ))
            ) : (
              <div className="px-3 py-2 text-[12px] text-[#9a9893]">目前没有卷外散札</div>
            )}
          </section>
        </div>

        <div className="border-t border-[rgba(0,0,0,0.05)] px-3 py-3">
          <div className="flex items-center gap-3 rounded-2xl px-3 py-2 hover:bg-[#E5E2D8]">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1a1a18] text-xs font-semibold text-white">D</div>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-[#1a1a18]">Daemon</div>
              <div className="mt-0.5 text-[11px] text-[#8d8b84]">Local prototype</div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function Hero({ slip, folioTitle, onRun }) {
  return (
    <div className="px-1 py-2">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Slip</div>
          <h1 className="portal-serif text-[1.92rem] leading-[2.25rem] text-[#1a1a18]">{slip.title}</h1>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <span className="rounded-full bg-[#ece9df] px-3 py-1 text-xs font-medium text-[#6b6a68]">{slip.stance}</span>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-2 rounded-full bg-[#f8f7f2] px-3 py-1.5 text-[12px] text-[#6b6a68]">
          <Folder width={13} height={13} />
          {folioTitle || "卷外"}
        </span>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onRun}
          className="inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
        >
          <Play width={15} height={15} />
          {slip.deed.status === "closed" ? "开始执行" : "进入当前 deed"}
        </button>
      </div>
    </div>
  );
}

function PlanCard({
  slip,
  editMode,
  onToggleEdit,
  onMoveStep,
  onAddStep,
  onCycleCadence,
  onToggleCadence,
  onOpenExpanded,
}) {
  const graph = buildMoveGraph(slip.structure);

  return (
    <div className="px-1 py-1">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
          <Waypoints width={16} height={16} />
          <span>Move 结构</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onOpenExpanded}
            title="查看全图"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
          >
            <Search width={15} height={15} />
          </button>
          <button
            type="button"
            onClick={onToggleEdit}
            title={editMode ? "退出整理" : "整理结构"}
            className={cx(
              "inline-flex h-9 w-9 items-center justify-center rounded-full transition",
              editMode ? "bg-[#1a1a18] text-white" : "bg-[#fbfaf7] text-[#6b6a68] hover:bg-white",
            )}
          >
            <SquarePen width={15} height={15} />
          </button>
          <button
            type="button"
            onClick={onToggleCadence}
            title={slip.cadence.enabled ? "停用节律" : "启用节律"}
            className={cx(
              "inline-flex h-9 w-9 items-center justify-center rounded-full transition hover:bg-white",
              slip.cadence.enabled ? "bg-[#ece9df] text-[#6b6a68]" : "bg-[#fbfaf7] text-[#a19f98]",
            )}
          >
            <Clock3 width={15} height={15} />
          </button>
          {slip.cadence.enabled ? (
            <button
              type="button"
              onClick={onCycleCadence}
              title="切换节律"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
            >
              <TimerReset width={15} height={15} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-4">
        <MoveGraphCanvas graph={graph} mode="structure" compact />
      </div>

      {editMode ? (
        <div className="mt-4 rounded-[1.35rem] bg-[#fbfaf7] p-4">
          <div className="space-y-2">
            {slip.structure.map((item, index) => (
              <div key={`${item}-${index}`} className="flex items-center gap-3 rounded-xl px-3 py-2">
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#f1eee5] text-[11px] text-[#6b6a68]">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-[#1a1a18]">{moveLabel(item, index)}</span>
                <button
                  type="button"
                  onClick={() => onMoveStep(index, -1)}
                  className="rounded-lg p-1.5 text-[#6b6a68] transition hover:bg-[#f1eee5]"
                >
                  <ArrowUp width={15} height={15} />
                </button>
                <button
                  type="button"
                  onClick={() => onMoveStep(index, 1)}
                  className="rounded-lg p-1.5 text-[#6b6a68] transition hover:bg-[#f1eee5]"
                >
                  <ArrowDown width={15} height={15} />
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={onAddStep}
            className="mt-3 inline-flex items-center gap-2 rounded-xl bg-[#f1eee5] px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#ebe5d7]"
          >
            <SquarePen width={15} height={15} />
            插入一步
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MoveGraphExpandedView({
  slip,
  editMode,
  onClose,
  onToggleEdit,
  onMoveStep,
  onAddStep,
  onCycleCadence,
  onToggleCadence,
}) {
  const graph = buildMoveGraph(slip.structure);

  return (
    <div className="fixed inset-0 z-40 overflow-y-auto bg-[#F5F5F0]/96 backdrop-blur-sm" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="mx-auto w-full max-w-[84rem] px-6 pb-10 pt-6">
        <div className="px-1">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
              <Waypoints width={16} height={16} />
              <span>Move 全图</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onToggleEdit}
                title={editMode ? "退出整理" : "整理结构"}
                className={cx(
                  "inline-flex h-9 w-9 items-center justify-center rounded-full transition",
                  editMode ? "bg-[#1a1a18] text-white" : "bg-[#fbfaf7] text-[#6b6a68] hover:bg-white",
                )}
              >
                <SquarePen width={15} height={15} />
              </button>
              <button
                type="button"
                onClick={onToggleCadence}
                title={slip.cadence.enabled ? "停用节律" : "启用节律"}
                className={cx(
                  "inline-flex h-9 w-9 items-center justify-center rounded-full transition hover:bg-white",
                  slip.cadence.enabled ? "bg-[#ece9df] text-[#6b6a68]" : "bg-[#fbfaf7] text-[#a19f98]",
                )}
              >
                <Clock3 width={15} height={15} />
              </button>
              {slip.cadence.enabled ? (
                <button
                  type="button"
                  onClick={onCycleCadence}
                  title="切换节律"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
                >
                  <TimerReset width={15} height={15} />
                </button>
              ) : null}
            </div>
          </div>

          <div className="mt-4">
            <MoveGraphCanvas graph={graph} mode="structure" />
          </div>

          {editMode ? (
            <div className="mt-4 rounded-[1.35rem] bg-[#fbfaf7] p-4">
              <div className="space-y-2">
                {slip.structure.map((item, index) => (
                  <div key={`${item}-${index}`} className="flex items-center gap-3 rounded-xl px-3 py-2">
                    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#f1eee5] text-[11px] text-[#6b6a68]">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-[#1a1a18]">{moveLabel(item, index)}</span>
                    <button
                      type="button"
                      onClick={() => onMoveStep(index, -1)}
                      className="rounded-lg p-1.5 text-[#6b6a68] transition hover:bg-[#f1eee5]"
                    >
                      <ArrowUp width={15} height={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => onMoveStep(index, 1)}
                      className="rounded-lg p-1.5 text-[#6b6a68] transition hover:bg-[#f1eee5]"
                    >
                      <ArrowDown width={15} height={15} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={onAddStep}
                className="mt-3 inline-flex items-center gap-2 rounded-xl bg-[#f1eee5] px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#ebe5d7]"
              >
                <SquarePen width={15} height={15} />
                插入一步
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DraftWorkspace({ draft, targetFolio, onCrystallize, onAbandon }) {
  return (
    <div className="mx-auto w-full max-w-[54rem]">
      <div className="relative pt-5">
        <div className="pointer-events-none absolute inset-x-8 top-6 h-[calc(100%-0.5rem)] rounded-[1.7rem] bg-[#efe8da] opacity-90" />
        <div className="pointer-events-none absolute inset-x-4 top-3 h-[calc(100%-0.5rem)] -rotate-[1.2deg] rounded-[1.7rem] border border-[rgba(0,0,0,0.04)] bg-[#f4eee2] opacity-80" />

        <div className="relative overflow-hidden rounded-[1.75rem] border border-[rgba(0,0,0,0.06)] bg-[#fbfaf7] shadow-claude">
          <div className="px-7 pb-6 pt-7">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-[#f1ece1] px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-[#8a6c45]">
                  Draft
                </div>
                <h1 className="portal-serif text-[2rem] leading-[2.35rem] text-[#1a1a18]">{draft.title}</h1>
                <p className="mt-3 max-w-2xl text-[15px] leading-7 text-[#6b6a68]">{draft.summary}</p>
              </div>
            </div>

            <div className="mt-8 rounded-[1.45rem] bg-[#f5f1e8] px-5 py-5">
              <div className="text-[15px] leading-[1.9rem] text-[#1a1a18]">{draft.currentScheme}</div>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-[#f8f6ef] px-3 py-1.5 text-[12px] text-[#6b6a68]">
                <Folder width={13} height={13} />
                {targetFolio?.title || "卷外"}
              </span>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onCrystallize}
                className="inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
              >
                <Check width={15} height={15} />
                成札
              </button>
              <button
                type="button"
                onClick={onAbandon}
                className="inline-flex items-center gap-2 rounded-xl bg-[#ece7dc] px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#e4ddcf]"
              >
                <TimerReset width={15} height={15} />
                放弃
              </button>
            </div>
          </div>

          {draft.materials.length ? (
            <div className="border-t border-[rgba(0,0,0,0.05)] bg-[#f8f6ef] px-7 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">材料</span>
                {draft.materials.map((item) => (
                  <span key={item} className="rounded-full bg-white px-3 py-1.5 text-[12px] text-[#6b6a68]">
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CadenceCard({ cadence, onCycleCadence, onToggleCadence }) {
  return (
    <SurfaceCard className="overflow-hidden">
      <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
        <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
          <Clock3 width={16} height={16} />
          <span>节律</span>
        </div>
      </div>
      <div className="px-6 py-5">
        <div className="rounded-2xl bg-[#f5f5f0] p-4">
          <div className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-xs font-medium text-[#6b6a68]">
            {cadence.enabled ? "已启用" : "已停用"} · {cadence.schedule}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onCycleCadence}
              className="inline-flex items-center gap-2 rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f8f7f2]"
            >
              <TimerReset width={15} height={15} />
              改节律
            </button>
            <button
              type="button"
              onClick={onToggleCadence}
              className="inline-flex items-center gap-2 rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f8f7f2]"
            >
              <TimerReset width={15} height={15} />
              {cadence.enabled ? "停用" : "启用"}
            </button>
          </div>
        </div>
      </div>
    </SurfaceCard>
  );
}

function ComparePanel({ deed, compareState, onChangeSide, onPromoteVersion, onClose }) {
  const left = deed.versions.find((item) => item.id === compareState.leftVersionId) || deed.versions[0];
  const right =
    deed.versions.find((item) => item.id === compareState.rightVersionId) ||
    deed.versions[Math.min(1, deed.versions.length - 1)] ||
    deed.versions[0];

  return (
    <SurfaceCard className="mt-6 overflow-hidden">
      <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
            <Layers3 width={16} height={16} />
            <span>候选产物</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[rgba(0,0,0,0.08)] bg-[#f5f5f0] px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#ecebe4]"
          >
            收起
          </button>
        </div>
      </div>

      <div className="grid gap-0 md:grid-cols-2">
        {[left, right].map((version, index) => (
          <div
            key={version.id}
            className={cx(
              "px-6 py-5",
              index === 0 ? "border-b border-[rgba(0,0,0,0.06)] md:border-b-0 md:border-r" : "",
            )}
          >
            <div className="flex flex-wrap gap-2">
              {deed.versions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => onChangeSide(index === 0 ? "leftVersionId" : "rightVersionId", option.id)}
                  className={cx(
                    "rounded-full px-3 py-1.5 text-[12px] transition",
                    option.id === version.id
                      ? "bg-[#1a1a18] text-white"
                      : "bg-[#f5f5f0] text-[#6b6a68] hover:bg-[#ecebe4]",
                  )}
                >
                  {option.name}
                </button>
              ))}
            </div>

            <div className="mt-4 rounded-[1.4rem] border border-[rgba(0,0,0,0.06)] bg-[#f8f7f2] p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-[#1a1a18]">{version.name}</div>
                {version.winning ? (
                  <span className="rounded-full bg-white px-2.5 py-1 text-[11px] text-[#8d8b84]">当前保留</span>
                ) : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="rounded-full bg-white px-2.5 py-1 text-[11px] text-[#6b6a68]">{deedArtifactLabel(deed)}</span>
              </div>
              <p className="mt-4 text-[14px] leading-6 text-[#1a1a18]">{shortText(version.excerpt, 120)}</p>
              <button
                type="button"
                onClick={() => onPromoteVersion(version.id)}
                className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#ecebe4]"
              >
                <Check width={15} height={15} />
                保留这一版
              </button>
            </div>
          </div>
        ))}
      </div>
    </SurfaceCard>
  );
}

function DeedList({ deeds, activeDeedId, onOpenDeed }) {
  return (
    <div className="mt-6 px-1">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
        <Layers3 width={16} height={16} />
        <span>Deeds</span>
      </div>
      <div className="space-y-2">
        {deeds.map((deed, index) => (
          <button
            key={deed.id}
            type="button"
            onClick={() => onOpenDeed(deed.id)}
            className={cx(
              "flex w-full items-center justify-between gap-4 rounded-[1.35rem] px-4 py-3 text-left transition",
              deed.id === activeDeedId ? "bg-[#e7e2d5]" : "bg-[#f1eee5] hover:bg-[#eae4d7]",
              deed.status === "closed" ? deedAgeOpacityClass(deed.updatedAt) : "",
            )}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[12px] text-[#8d8b84]">{index === 0 ? "当前" : "过往"}</span>
                <span className={cx("inline-flex h-2.5 w-2.5 rounded-full", slipStatusDot(deed.status))} />
                <span className="text-sm font-medium text-[#1a1a18]">{deedStatusLabel(deed.status)}</span>
                {deed.status === "closed" ? (
                  <span className="rounded-full bg-[#fbfaf7] px-2.5 py-1 text-[11px] text-[#6b6a68]">{deedArtifactLabel(deed)}</span>
                ) : null}
              </div>
              <div className="mt-2 text-[12px] text-[#8d8b84]">{formatDateTime(deed.updatedAt)}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function DeedCard({
  structure,
  deed,
  onOpenCompare,
}) {
  const currentVersion = deed.versions.find((item) => item.id === deed.selectedVersionId) || deed.versions[0];
  const graph = buildMoveGraph(structure);
  const progress = moveProgress(deed, graph.nodes.length);
  const activeMove = graph.nodes[progress.activeIndex] || graph.nodes[graph.nodes.length - 1];
  const isClosed = deed.status === "closed";
  const canCompare = deed.status === "settling" && deed.versions.length > 1;

  return (
    <div className="mt-6 px-1 py-1">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">执行流</div>
          <div className="mt-2 portal-serif text-[1.28rem] leading-8 text-[#1a1a18]">Deed</div>
        </div>
        <span className={cx("rounded-full px-3 py-1 text-xs font-medium", deedStatusTone(deed.status))}>
          {deedStatusLabel(deed.status)}
        </span>
      </div>

      <div className="mt-4">
        <MoveGraphCanvas graph={graph} progress={progress} mode="deed" deedStatus={deed.status} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-2 rounded-full bg-[#fbfaf7] px-3 py-1.5 text-[12px] text-[#6b6a68]">
            <Waypoints width={13} height={13} />
            {activeMove?.title || "尚未开始"}
          </span>
          <span className="rounded-full bg-[#fbfaf7] px-3 py-1.5 text-[12px] text-[#6b6a68]">
            {isClosed ? deedArtifactLabel(deed) : currentVersion?.name || "未定"}
          </span>
          <span className="rounded-full bg-[#fbfaf7] px-3 py-1.5 text-[12px] text-[#6b6a68]">
            {deed.status === "settling" ? `${deed.versions.length} 个候选` : deed.status === "closed" ? "已收束" : "进行中"}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {canCompare ? (
            <button
              type="button"
              onClick={onOpenCompare}
              className="inline-flex items-center gap-2 rounded-xl bg-[#fbfaf7] px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-white"
            >
              <Layers3 width={15} height={15} />
              比较
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DeedExpandedView({
  slip,
  deed,
  messages,
  compareState,
  onBack,
  onToggleCompare,
  onPromoteVersion,
  onChangeCompareSide,
  onCloseCompare,
  composerValue,
  onComposerChange,
  onComposerSubmit,
  onComposerHistoryUp,
  composerDisabled,
  composerLoading,
  attachmentLabel,
  onAttachClick,
  onRetryMessage,
  onEditMessage,
  onCopyMessage,
  onRateMessage,
  copiedMessageId,
  dockFocused,
  onDockFocusChange,
}) {
  return (
    <div className="fixed inset-0 z-40 overflow-y-auto bg-[#F5F5F0]/96 backdrop-blur-sm" onMouseDown={(event) => event.target === event.currentTarget && onBack()}>
      <div className="relative mx-auto flex h-full w-full max-w-[72rem] flex-col px-6 pb-6 pt-6">
        <div className="min-h-0 flex-1 overflow-y-auto pb-32" onPointerDownCapture={() => onDockFocusChange?.(false)}>
          <div className="mb-5 flex items-center justify-between gap-4 px-1">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Deed</div>
              <div className="mt-2 portal-serif text-[1.5rem] leading-8 text-[#1a1a18]">{slip.title}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className={cx("rounded-full px-3 py-1 text-xs font-medium", deedStatusTone(deed.status))}>
                {deedStatusLabel(deed.status)}
              </span>
              {deed.status === "closed" ? (
                <span className="rounded-full bg-[#fbfaf7] px-3 py-1 text-[11px] text-[#8d8b84]">{deedArtifactLabel(deed)}</span>
              ) : null}
            </div>
          </div>

          <DeedCard structure={slip.structure} deed={deed} onOpenCompare={onToggleCompare} />

          {compareState.open && deed.status === "settling" ? (
            <ComparePanel
              deed={deed}
              compareState={compareState}
              onChangeSide={onChangeCompareSide}
              onPromoteVersion={onPromoteVersion}
              onClose={onCloseCompare}
            />
          ) : null}
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
          <ConversationDock
            ownerLabel="Deed"
            focused={dockFocused}
            onFocusChange={onDockFocusChange}
            messages={messages}
            composerValue={composerValue}
            onComposerChange={onComposerChange}
            onComposerSubmit={onComposerSubmit}
            onComposerHistoryUp={onComposerHistoryUp}
            composerDisabled={composerDisabled}
            composerLoading={composerLoading}
            attachmentLabel={attachmentLabel}
            onAttachClick={onAttachClick}
            onRetryMessage={onRetryMessage}
            onEditMessage={onEditMessage}
            onCopyMessage={onCopyMessage}
            onRateMessage={onRateMessage}
            copiedMessageId={copiedMessageId}
          />
        </div>
      </div>
    </div>
  );
}

function SlipWorkspace({
  slip,
  folio,
  deeds,
  activeDeedId,
  structureMode,
  onRun,
  onOpenDeed,
  onToggleStructureMode,
  onMoveStructure,
  onAddStructureStep,
  onCycleCadence,
  onToggleCadence,
  onOpenMoveExpanded,
}) {
  return (
    <>
      <Hero
        slip={slip}
        folioTitle={folio?.title}
        onRun={onRun}
      />

      <div className="mt-6">
        <PlanCard
          slip={slip}
          editMode={structureMode}
          onToggleEdit={onToggleStructureMode}
          onMoveStep={onMoveStructure}
          onAddStep={onAddStructureStep}
          onCycleCadence={onCycleCadence}
          onToggleCadence={onToggleCadence}
          onOpenExpanded={onOpenMoveExpanded}
        />
      </div>

      <DeedList deeds={deeds} activeDeedId={activeDeedId} onOpenDeed={onOpenDeed} />
    </>
  );
}

function FolioBoard({
  slips,
  edges,
  compact = false,
  onSelectSlip,
  onToggleClock,
  onDetailClick,
}) {
  const cardWidth = compact ? 148 : 192;
  const cardHeight = compact ? 92 : 142;
  const rowCount = compact ? 2 : slips.length <= 6 ? 2 : 3;
  const gapX = compact ? 32 : 64;
  const gapY = compact ? 34 : 68;
  const boardPadding = compact ? 32 : 48;
  const nodes = slips.map((slip, index) => {
    const column = Math.floor(index / rowCount);
    const row = index % rowCount;
    const offsetX = compact ? (row % 2 === 1 ? 10 : 0) : row === 1 ? 18 : row === 2 ? 6 : 0;
    return {
      slip,
      left: boardPadding + column * (cardWidth + gapX) + offsetX,
      top: (compact ? 28 : 40) + row * (cardHeight + gapY),
    };
  });
  const boardWidth = Math.max(
    compact ? 600 : 860,
    nodes.reduce((current, node) => Math.max(current, node.left + cardWidth + boardPadding), 0),
  );
  const boardHeight = Math.max(compact ? 248 : 430, (compact ? 28 : 40) + rowCount * (cardHeight + gapY));

  function nodeCenter(node) {
    return {
      x: node.left + cardWidth / 2,
      y: node.top + cardHeight / 2,
    };
  }

  return (
    <div>
      <div className="px-1 pb-3 pt-1">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm font-medium text-[#63635e]">
            <FolderOpen width={16} height={16} />
            <span>{compact ? "卷内视图" : "卷内全图"}</span>
          </div>
          {onDetailClick ? (
            <button
              type="button"
              onClick={onDetailClick}
              title="查看卷内全图"
              className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#fdfcf9] text-[#63635e] transition hover:bg-white"
            >
              <Search width={15} height={15} />
            </button>
          ) : null}
        </div>
      </div>
      <div className="overflow-x-auto px-3 pb-3">
        <div
          className="relative min-w-full rounded-[1.6rem]"
          style={{
            width: `${boardWidth}px`,
            height: `${boardHeight}px`,
            background: GRAPH_TOKENS.canvas,
            boxShadow: "inset 0 0 0 1px rgba(41,41,41,0.06)",
          }}
        >
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(173,173,173,0.14)_1px,transparent_0)] bg-[length:22px_22px] opacity-[0.08]" />
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox={`0 0 ${boardWidth} ${boardHeight}`}
            preserveAspectRatio="none"
          >
          {edges.map(([fromId, toId]) => {
            const fromNode = nodes.find((node) => node.slip.id === fromId);
            const toNode = nodes.find((node) => node.slip.id === toId);
            if (!fromNode || !toNode) return null;
            const start = nodeCenter(fromNode);
            const end = nodeCenter(toNode);
            const midY = (start.y + end.y) / 2;
            return (
              <path
                key={`${fromId}-${toId}`}
                d={`M ${start.x} ${start.y} C ${start.x} ${midY}, ${end.x} ${midY}, ${end.x} ${end.y}`}
                fill="none"
                stroke={GRAPH_TOKENS.lineDefault}
                strokeWidth={compact ? "1.2" : "1.6"}
                strokeLinecap="round"
              />
            );
          })}
          </svg>

          {nodes.map((node) => (
            <div
              key={node.slip.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectSlip(node.slip.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectSlip(node.slip.id);
                }
              }}
              className={cx(
                "absolute border px-5 text-left transition duration-150 hover:-translate-y-[1px]",
                compact ? "rounded-[1.6rem] px-4 py-[0.9rem]" : "rounded-[1.85rem] px-[1.1rem] py-[1.05rem]",
              )}
              style={{
                left: `${node.left}px`,
                top: `${node.top}px`,
                width: `${cardWidth}px`,
                minHeight: `${cardHeight}px`,
                borderColor: "rgba(173,173,173,0.54)",
                color: GRAPH_TOKENS.textPrimary,
                background: `linear-gradient(180deg, rgba(255,255,255,0.94) 0px, rgba(255,255,255,0.44) 22px, rgba(255,255,255,0) 46px), linear-gradient(180deg, rgba(255,255,255,0) 60%, rgba(41,41,41,0.02) 100%), ${GRAPH_TOKENS.cardSurface}`,
                boxShadow: GRAPH_RELIEF.folioCard,
              }}
            >
              {compact ? (
                <div className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <span
                      className="inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2"
                      style={{
                        background: "rgba(255,255,255,0.76)",
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.86), 0 3px 6px rgba(41,41,41,0.04)",
                      }}
                    >
                      <span className={cx("inline-flex h-2.5 w-2.5 shrink-0 rounded-full", slipStatusDot(node.slip.deed.status))} />
                    </span>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleClock(node.slip.id);
                      }}
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition hover:bg-white"
                      style={{
                        borderColor: "rgba(41,41,41,0.08)",
                        background: node.slip.cadence.enabled ? "rgba(174,86,48,0.08)" : "rgba(255,255,255,0.78)",
                        color: node.slip.cadence.enabled ? GRAPH_TOKENS.activeTone : GRAPH_TOKENS.visitedTone,
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.84)",
                      }}
                      title="切换节律"
                    >
                      <Clock3 width={11} height={11} />
                    </button>
                  </div>
                  <div className="mt-3 min-w-0">
                    <span className="line-clamp-2 text-[13.2px] font-medium leading-[1.16] text-[#292929]">{node.slip.title}</span>
                  </div>
                  <div className="mt-auto pt-3">
                    <div className="h-px rounded-full bg-[rgba(41,41,41,0.06)]" />
                  </div>
                </div>
              ) : (
                <div className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <span
                      className="inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2"
                      style={{
                        background: "rgba(255,255,255,0.76)",
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.86), 0 3px 6px rgba(41,41,41,0.04)",
                      }}
                    >
                      <span className={cx("inline-flex h-2.5 w-2.5 shrink-0 rounded-full", slipStatusDot(node.slip.deed.status))} />
                    </span>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleClock(node.slip.id);
                      }}
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition hover:bg-white"
                      style={{
                        borderColor: "rgba(41,41,41,0.08)",
                        background: node.slip.cadence.enabled ? "rgba(174,86,48,0.08)" : "rgba(255,255,255,0.78)",
                        color: node.slip.cadence.enabled ? GRAPH_TOKENS.activeTone : GRAPH_TOKENS.visitedTone,
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.84)",
                      }}
                      title="切换节律"
                    >
                      <Clock3 width={11} height={11} />
                    </button>
                  </div>
                  <div className="mt-3 min-w-0">
                    <div className="line-clamp-2 text-[14px] font-medium leading-[1.16] text-[#292929]">{node.slip.title}</div>
                    <div className="mt-2 line-clamp-2 text-[12px] leading-[1.42] text-[#5F5B56]">{node.slip.summary}</div>
                  </div>
                  <div className="mt-auto pt-3">
                    <div className="h-px rounded-full bg-[rgba(41,41,41,0.06)]" />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FolioWorkspace({
  folio,
  slips,
  looseSlips,
  content,
  edges,
  expanded,
  organizeMode,
  onOpenExpanded,
  onCloseExpanded,
  onToggleOrganize,
  onOpenSlip,
  onToggleClock,
  onMoveSlip,
  onDetachSlip,
  onAttachSlip,
  onCreateSlip,
  onRetryMessage,
  onEditMessage,
  onCopyMessage,
  onRateMessage,
  copiedMessageId,
}) {
  return (
    <>
      <div className="px-1 py-2">
        <div className="mb-2 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Folio</div>
            <h1 className="portal-serif text-[1.92rem] leading-[2.25rem] text-[#1a1a18]">{folio.title}</h1>
            <p className="mt-3 max-w-3xl text-[15px] leading-[1.72rem] text-[#6b6a68]">{folio.note}</p>
          </div>
          <button
            type="button"
            onClick={onToggleOrganize}
            className={cx(
              "rounded-full px-3 py-1 text-xs font-medium transition",
              organizeMode ? "bg-[#1a1a18] text-white" : "bg-[#ece9df] text-[#6b6a68]",
            )}
          >
            {organizeMode ? "退出整理" : "整理"}
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onCreateSlip}
            className="inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
          >
            <SquarePen width={15} height={15} />
            在卷内新建
          </button>
          <span className="inline-flex items-center gap-2 rounded-full bg-[#f1eee5] px-3 py-1.5 text-[12px] text-[#6b6a68]">
            <LibraryBig width={14} height={14} />
            {slips.length} 张签札
          </span>
        </div>
      </div>

      <div className="mt-6">
        <FolioBoard
          slips={slips}
          edges={edges}
          compact
          onSelectSlip={onOpenSlip}
          onToggleClock={onToggleClock}
          onDetailClick={onOpenExpanded}
        />
      </div>

      {organizeMode ? (
        <div className="mt-6 grid gap-6 md:grid-cols-[1fr_1fr]">
          <SurfaceCard className="overflow-hidden">
            <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
              <div className="text-sm font-medium text-[#1a1a18]">卷内序列</div>
            </div>
            <div className="px-6 py-5">
              <div className="space-y-3">
                {slips.map((slip, index) => (
                  <div key={slip.id} className="rounded-2xl bg-[#f8f7f2] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-[#1a1a18]">{slip.title}</div>
                        <div className="mt-1 text-[12px] text-[#8d8b84]">位置 {index + 1}</div>
                      </div>
                      <span className={cx("inline-flex h-2.5 w-2.5 rounded-full", slipStatusDot(slip.deed.status))} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => onMoveSlip(slip.id, -1)}
                        className="rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f1efe7]"
                      >
                        上移
                      </button>
                      <button
                        type="button"
                        onClick={() => onMoveSlip(slip.id, 1)}
                        className="rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f1efe7]"
                      >
                        下移
                      </button>
                      <button
                        type="button"
                        onClick={() => onDetachSlip(slip.id)}
                        className="rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f1efe7]"
                      >
                        取出卷
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </SurfaceCard>

          <SurfaceCard className="overflow-hidden">
            <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
              <div className="text-sm font-medium text-[#1a1a18]">卷外待收入</div>
            </div>
            <div className="px-6 py-5">
              {looseSlips.length ? (
                <div className="space-y-3">
                  {looseSlips.map((slip) => (
                    <div key={slip.id} className="rounded-2xl bg-[#f8f7f2] p-4">
                      <div className="text-sm font-medium text-[#1a1a18]">{slip.title}</div>
                      <p className="mt-1 text-[13.5px] leading-6 text-[#6b6a68]">{slip.summary}</p>
                      <button
                        type="button"
                        onClick={() => onAttachSlip(slip.id)}
                        className="mt-3 rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm text-[#1a1a18] transition hover:bg-[#f1efe7]"
                      >
                        收入此卷
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-2xl bg-[#f8f7f2] p-4 text-[13.5px] leading-6 text-[#6b6a68]">
                  目前没有卷外散札。你可以从侧栏新建一张草稿，成札后再收入本卷。
                </div>
              )}
            </div>
          </SurfaceCard>
        </div>
      ) : null}

      {expanded ? (
        <div
          className="fixed inset-0 z-40 overflow-y-auto bg-[#F5F5F0]/96 backdrop-blur-sm"
          onMouseDown={(event) => event.target === event.currentTarget && onCloseExpanded()}
        >
          <div className="mx-auto w-full max-w-[84rem] px-6 pb-10 pt-6">
            <FolioBoard slips={slips} edges={edges} onSelectSlip={onOpenSlip} onToggleClock={onToggleClock} />
          </div>
        </div>
      ) : null}
    </>
  );
}

function buildAssistantReply(owner, subjectTitle, text, selectedVersion) {
  const clean = String(text || "").trim();
  if (owner === "Deed") {
    return `我把这句按比较视角收成一句：当前更适合保留 **${selectedVersion?.name || "当前版本"}**，因为它更接近“${shortText(
      clean,
      28,
    )}”这条判断。`;
  }
  if (owner === "Draft") {
    return `我把这条收进当前草稿方案：${shortText(clean, 54)}。现在还不急着执行，先把它收敛成一张能成札的对象。`;
  }
  if (owner === "Folio") {
    return `我把这条记成卷内安排：${shortText(clean, 54)}。后续应优先通过整理模式去改卷内结构，而不是全靠对话框硬做。`;
  }
  return `我先把这条补记并回 ${subjectTitle} 的主线：${shortText(clean, 56)}。如果你继续点“再运行”，这条修改会在假 deed 里重新收束一次。`;
}

export default function MockPortal() {
  const [drafts, setDrafts] = useState(INITIAL_DRAFTS);
  const [folioThreads, setFolioThreads] = useState(FOLIO_CONTENT);
  const [folios, setFolios] = useState(INITIAL_FOLIOS);
  const [slips, setSlips] = useState(INITIAL_SLIPS);
  const [deedHistoryBySlipId, setDeedHistoryBySlipId] = useState(INITIAL_DEED_HISTORY);
  const [deedThreads, setDeedThreads] = useState(INITIAL_DEED_THREADS);
  const [folioEdges, setFolioEdges] = useState(INITIAL_FOLIO_EDGES);
  const [folioFocusById, setFolioFocusById] = useState(INITIAL_FOLIO_FOCUS);
  const [pendingEdgeStartByFolio, setPendingEdgeStartByFolio] = useState({});
  const [selectedTarget, setSelectedTarget] = useState({ kind: "slip", id: "slip_taskgroup" });
  const [searchQuery, setSearchQuery] = useState("");
  const [composerValue, setComposerValue] = useState("把最后那段和 gather 的对照再压短一点。");
  const [composerHistory, setComposerHistory] = useState([]);
  const [composerHistoryIndex, setComposerHistoryIndex] = useState(-1);
  const [attachmentLabel, setAttachmentLabel] = useState("");
  const [toast, setToast] = useState("");
  const [structureMode, setStructureMode] = useState(false);
  const [organizeMode, setOrganizeMode] = useState(false);
  const [compareState, setCompareState] = useState({
    open: false,
    leftVersionId: "v2",
    rightVersionId: "v1",
  });
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [pendingRun, setPendingRun] = useState(null);
  const [replyingSlipId, setReplyingSlipId] = useState("");
  const [returnTarget, setReturnTarget] = useState(null);
  const [expandedDeedSlipId, setExpandedDeedSlipId] = useState("");
  const [selectedDeedId, setSelectedDeedId] = useState("");
  const [expandedFolioId, setExpandedFolioId] = useState("");
  const [expandedMoveSlipId, setExpandedMoveSlipId] = useState("");
  const [dockFocused, setDockFocused] = useState(false);
  const [deedDockFocused, setDeedDockFocused] = useState(false);

  const deferredQuery = useDeferredValue(searchQuery);
  const normalizedQuery = deferredQuery.trim().toLowerCase();
  const deskDrafts = drafts.slice(0, 3);
  const filteredFolios = folios.filter((folio) => {
    if (!normalizedQuery) return true;
    return `${folio.title} ${folio.summary}`.toLowerCase().includes(normalizedQuery);
  });
  const filteredSlips = slips.filter((slip) => {
    if (!normalizedQuery) return true;
    return `${slip.title} ${slip.summary} ${slip.objective}`.toLowerCase().includes(normalizedQuery);
  });
  const filteredLooseSlips = filteredSlips.filter((slip) => !slip.folioId);

  const activeDraft = selectedTarget.kind === "draft" ? drafts.find((item) => item.id === selectedTarget.id) || drafts[0] : null;
  const activeSlip = selectedTarget.kind === "slip" ? slips.find((item) => item.id === selectedTarget.id) || slips[0] : null;
  const activeSlipDeeds = activeSlip
    ? [activeSlip.deed, ...(deedHistoryBySlipId[activeSlip.id] || [])].sort(
        (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
      )
    : [];
  const activeDeed = activeSlipDeeds.find((item) => item.id === selectedDeedId) || null;
  const activeFolio =
    selectedTarget.kind === "folio" ? folios.find((item) => item.id === selectedTarget.id) || folios[0] : null;
  const currentFolio = activeDraft
    ? folios.find((item) => item.id === activeDraft.targetFolioId) || null
    : activeSlip
      ? folios.find((item) => item.id === activeSlip.folioId) || null
      : activeFolio;
  const activeFolioId = activeFolio?.id || "";
  const activeFolioSlipIdsKey = activeFolio?.slipIds.join("|") || "";
  const focusedSlipId = activeFolio
    ? folioFocusById[activeFolio.id] && activeFolio.slipIds.includes(folioFocusById[activeFolio.id])
      ? folioFocusById[activeFolio.id]
      : activeFolio.slipIds[0] || ""
    : "";
  const pendingEdgeSlipId = activeFolio ? pendingEdgeStartByFolio[activeFolio.id] || "" : "";

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(""), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!copiedMessageId) return undefined;
    const timer = window.setTimeout(() => setCopiedMessageId(""), 1200);
    return () => window.clearTimeout(timer);
  }, [copiedMessageId]);

  useEffect(() => {
    if (selectedTarget.kind !== "slip") {
      setExpandedDeedSlipId("");
      setSelectedDeedId("");
    }
    if (selectedTarget.kind !== "folio") {
      setExpandedFolioId("");
    }
  }, [selectedTarget.kind]);

  useEffect(() => {
    setDockFocused(false);
  }, [selectedTarget.kind, selectedTarget.id]);

  useEffect(() => {
    setDeedDockFocused(false);
  }, [expandedDeedSlipId, selectedDeedId]);

  useEffect(() => {
    const deedForPanel = activeDeed || activeSlip?.deed;
    if (!deedForPanel) return;
    const fallbackVersion = deedForPanel.versions[0];
    const rightVersion =
      deedForPanel.versions.find((item) => item.id !== deedForPanel.selectedVersionId)?.id || fallbackVersion?.id || "";

    setCompareState((current) => ({
      open: current.open && selectedTarget.kind === "slip" && Boolean(selectedDeedId) ? current.open : false,
      leftVersionId: deedForPanel.selectedVersionId || fallbackVersion?.id || "",
      rightVersionId: rightVersion,
    }));
  }, [activeSlip?.id, activeSlip?.deed?.id, activeDeed?.id, selectedTarget.kind, selectedTarget.id, selectedDeedId]);

  useEffect(() => {
    setStructureMode(false);
  }, [selectedTarget.kind, selectedTarget.id]);

  useEffect(() => {
    if (!activeFolioId) return;
    const firstSlipId = activeFolio?.slipIds[0] || "";
    setFolioFocusById((current) => {
      const currentFocus = current[activeFolioId];
      if (currentFocus && activeFolio?.slipIds.includes(currentFocus)) return current;
      return { ...current, [activeFolioId]: firstSlipId };
    });
    setPendingEdgeStartByFolio((current) => {
      const currentPending = current[activeFolioId];
      if (!currentPending || activeFolio?.slipIds.includes(currentPending)) return current;
      return { ...current, [activeFolioId]: "" };
    });
  }, [activeFolioId, activeFolioSlipIdsKey]);

  useEffect(() => {
    if (!pendingRun) return undefined;

    const timer = window.setTimeout(() => {
      setSlips((current) =>
        current.map((slip) => {
          if (slip.id !== pendingRun.slipId) return slip;
          if (slip.deed.id !== pendingRun.deedId) return slip;

          const nextIndex = slip.deed.versions.length;
          const nextVersionId = `v${nextIndex + 1}`;
          const nextVersion = {
            id: nextVersionId,
            name: versionName(nextIndex),
            note: "新一轮前端假执行生成的候选版本。",
            excerpt: `这轮假执行把“${pendingRun.prompt}”并进正文，并把结论收得更像故障现场卡片。`,
            winning: false,
          };
          const nextFile = {
            id: makeId("file"),
            name: `draft-${nextIndex + 1}-notes.md`,
            content: `## Fake Run ${nextIndex + 1}\n\n这是一份前端假执行生成的结果文件，收进了最新补记：${pendingRun.prompt}`,
          };

          return {
            ...slip,
            updatedAt: new Date().toISOString(),
            deed: {
              ...slip.deed,
              status: "settling",
              updatedAt: new Date().toISOString(),
              feedback: "待确认",
              selectedVersionId: nextVersionId,
              versions: [...slip.deed.versions.map((item) => ({ ...item, winning: false })), nextVersion],
              files: [nextFile, ...slip.deed.files],
            },
          };
        }),
      );
      appendDeedThread(pendingRun.deedId, {
        message_id: makeId("msg"),
        role: "assistant",
        content: "这一轮已经进入待比较阶段。现在只看候选和保留，不再改 Slip 本身。",
        created_utc: new Date().toISOString(),
      });
      setPendingRun(null);
      setReplyingSlipId("");
      setToast("假执行已收束到待比较状态。");
    }, 900);

    return () => window.clearTimeout(timer);
  }, [pendingRun]);

  function updateSlip(slipId, updater) {
    setSlips((current) =>
      current.map((slip) => {
        if (slip.id !== slipId) return slip;
        return updater(slip);
      }),
    );
  }

  function updateDeedInSlip(slipId, deedId, updater) {
    setSlips((current) =>
      current.map((slip) => {
        if (slip.id !== slipId) return slip;
        if (slip.deed.id !== deedId) return slip;
        return { ...slip, deed: updater(slip.deed), updatedAt: new Date().toISOString() };
      }),
    );
    setDeedHistoryBySlipId((current) => {
      const deeds = current[slipId] || [];
      if (!deeds.some((item) => item.id === deedId)) return current;
      return {
        ...current,
        [slipId]: deeds.map((deed) => (deed.id === deedId ? updater(deed) : deed)),
      };
    });
  }

  function appendDeedThread(deedId, message) {
    setDeedThreads((current) => ({
      ...current,
      [deedId]: [...(current[deedId] || []), message],
    }));
  }

  function updateFolio(folioId, updater) {
    setFolios((current) =>
      current.map((folio) => {
        if (folio.id !== folioId) return folio;
        return updater(folio);
      }),
    );
  }

  function updateDraft(draftId, updater) {
    setDrafts((current) =>
      current.map((draft) => {
        if (draft.id !== draftId) return draft;
        return updater(draft);
      }),
    );
  }

  function selectSlipDirect(slipId) {
    setReturnTarget(null);
    setExpandedDeedSlipId("");
    setSelectedDeedId("");
    setCompareState((current) => ({ ...current, open: false }));
    setSelectedTarget({ kind: "slip", id: slipId });
  }

  function openSlipFromFolio(slipId, options = {}) {
    const folioId = options.folioId || activeFolio?.id || slips.find((item) => item.id === slipId)?.folioId || "";
    setExpandedFolioId("");
    setExpandedDeedSlipId("");
    setSelectedDeedId("");
    setCompareState((current) => ({ ...current, open: false }));
    setReturnTarget(folioId ? { kind: "folio", id: folioId, expanded: Boolean(options.expanded) } : null);
    setSelectedTarget({ kind: "slip", id: slipId });
  }

  function handleBackToReturnTarget() {
    if (returnTarget?.kind === "folio" && returnTarget.id) {
      setSelectedTarget({ kind: "folio", id: returnTarget.id });
      setExpandedFolioId(returnTarget.expanded ? returnTarget.id : "");
      setExpandedDeedSlipId("");
      setSelectedDeedId("");
      setCompareState((current) => ({ ...current, open: false }));
      return;
    }
    if (currentFolio?.id) {
      setExpandedDeedSlipId("");
      setSelectedDeedId("");
      setCompareState((current) => ({ ...current, open: false }));
      setSelectedTarget({ kind: "folio", id: currentFolio.id });
    }
  }

  function toggleEdgeInFolio(folioId, fromId, toId) {
    if (!folioId || !fromId || !toId || fromId === toId) return;
    const [edgeFrom, edgeTo] = canonicalEdge(fromId, toId);
    setFolioEdges((current) => {
      const currentEdges = current[folioId] || [];
      const exists = currentEdges.some(([left, right]) => left === edgeFrom && right === edgeTo);
      return {
        ...current,
        [folioId]: exists
          ? currentEdges.filter(([left, right]) => !(left === edgeFrom && right === edgeTo))
          : [...currentEdges, [edgeFrom, edgeTo]],
      };
    });
  }

  function handleCreateDraft(targetFolioId = "") {
    const draftId = makeId("draft");
    const now = new Date().toISOString();
    const newDraft = {
      id: draftId,
      title: "新建草稿",
      summary: "这是一张尚未成札的对象，先在这里收敛目标。",
      convergence: "目标待收窄",
      currentScheme: "先把问题边界收窄成一张 `Slip` 能装下的范围，再决定是否成札。",
      priorDesigns: ["刚创建，还没有旧方案。"],
      materials: attachmentLabel ? [attachmentLabel] : [],
      targetFolioId,
      messages: [
        {
          message_id: makeId("msg"),
          role: "assistant",
          content: "这是一个新的 `Draft`。现在的输入口 owner 是这张草稿，不是 `Slip` 或 `Deed`。",
          created_utc: now,
        },
      ],
    };
    setDrafts((current) => [newDraft, ...current]);
    setSelectedTarget({ kind: "draft", id: draftId });
    handleComposerChange("先把这件事的边界收窄成一张签札。");
    setToast("已新建一张草稿。");
  }

  function handleCrystallizeDraft() {
    if (!activeDraft) return;
    const slipId = makeId("slip");
    const now = new Date().toISOString();
    const targetFolioId = String(activeDraft.targetFolioId || "").trim();
    const content = activeDraft.currentScheme.replace(/`/g, "");
    const newSlip = {
      id: slipId,
      title: activeDraft.title,
      summary: activeDraft.summary,
      objective: content,
      stance: "在场",
      updatedAt: now,
      folioId: targetFolioId,
      cadence: {
        enabled: false,
        schedule: CADENCE_OPTIONS[0],
      },
      structure: [
        "把草稿里的当前方案压成稳定签札题头。",
        "补出最小 plan card。",
        "等待第一次 deed 再产出正式结果。",
      ],
      deed: {
        id: makeId("deed_mock"),
        status: "closed",
        createdAt: now,
        updatedAt: now,
        feedback: "尚未执行",
        selectedVersionId: "v1",
        versions: [
          {
            id: "v1",
            name: "版本 A",
            note: "由草稿成札后形成的初始版本。",
            excerpt: content,
            winning: true,
          },
        ],
        files: [
          {
            id: makeId("file"),
            name: "slip-seed.md",
            content: `## Slip Seed\n\n${content}`,
          },
        ],
      },
      messages: [
        {
          message_id: makeId("msg"),
          role: "assistant",
          content: "这张札由当前草稿收束而来。普通噪声对话不会保留到成札后。",
          created_utc: now,
        },
      ],
    };

    setSlips((current) => [newSlip, ...current]);
    if (targetFolioId) {
      updateFolio(targetFolioId, (folio) => ({ ...folio, slipIds: [slipId, ...folio.slipIds] }));
    }
    setDrafts((current) => current.filter((draft) => draft.id !== activeDraft.id));
    selectSlipDirect(slipId);
    setToast("草稿已成札。");
  }

  function handleAbandonDraft() {
    if (!activeDraft) return;
    setDrafts((current) => current.filter((draft) => draft.id !== activeDraft.id));
    selectSlipDirect(slips[0]?.id || "");
    setToast("草稿已放弃，噪声对话随之删除。");
  }

  function handleCreateSlip(options = {}) {
    const requestedFolioId = String(options.folioId || "").trim();
    const keepFocusOnFolio = Boolean(options.keepFocusOnFolio);
    const slipId = makeId("slip_mock");
    const attachedFolioId = requestedFolioId || (selectedTarget.kind === "folio" ? selectedTarget.id : activeSlip?.folioId || "");
    const now = new Date().toISOString();
    const newSlip = {
      id: slipId,
      title: "新建假札",
      summary: "这是一张只在前端内存里存在的新札。",
      objective: "用来检查 Portal 里新建对象后，标题、结构、deed 和对话区如何一起更新。",
      stance: "在场",
      updatedAt: now,
      folioId: attachedFolioId,
      cadence: {
        enabled: false,
        schedule: CADENCE_OPTIONS[0],
      },
      structure: [
        "先写出这张札要回答的问题。",
        "补一条结构，把对象和 deed 接起来。",
      ],
      deed: {
        id: makeId("deed_mock"),
        status: "closed",
        createdAt: now,
        updatedAt: now,
        feedback: "尚未启动",
        selectedVersionId: "v1",
        versions: [
          {
            id: "v1",
            name: "版本 A",
            note: "空白初稿。",
            excerpt: "这是新建对象后的默认版本。",
            winning: true,
          },
        ],
        files: [
          {
            id: makeId("file"),
            name: "new-slip-outline.md",
            content: "## New Slip\n\n这是一张刚创建出来的前端假札。",
          },
        ],
      },
      messages: [
        {
          message_id: makeId("msg"),
          role: "assistant",
          content: "这张札刚刚创建出来。你现在可以直接补记、启动假执行，或者把它并入卷宗。",
          created_utc: now,
        },
      ],
    };

    startTransition(() => setSlips((current) => [newSlip, ...current]));
    if (attachedFolioId) {
      updateFolio(attachedFolioId, (folio) => ({ ...folio, slipIds: [slipId, ...folio.slipIds] }));
      setFolioFocusById((current) => ({ ...current, [attachedFolioId]: slipId }));
    }
    if (attachedFolioId && keepFocusOnFolio) {
      setSelectedTarget({ kind: "folio", id: attachedFolioId });
    } else {
      selectSlipDirect(slipId);
    }
    handleComposerChange("先把这张新札的主线压成三句话。");
    setToast("已新建一张前端假札。");
  }

  function handleShuffle() {
    if (!slips.length) return;
    const currentIndex = slips.findIndex((item) => item.id === activeSlip?.id);
    const next = slips[(currentIndex + 1 + slips.length) % slips.length];
    selectSlipDirect(next.id);
    setToast(`已切到 ${next.title}`);
  }

  function handleToggleCompare() {
    const deedForPanel = activeDeed || activeSlip?.deed;
    if (!activeSlip || !deedForPanel || deedForPanel.status === "closed") return;
    setSelectedDeedId(deedForPanel.id);
    setExpandedDeedSlipId(activeSlip.id);
    setCompareState((current) => ({ ...current, open: !current.open }));
  }

  function handleOpenActiveDeed(deedId = activeSlip?.deed?.id || "") {
    if (!activeSlip || !deedId) return;
    setSelectedDeedId(deedId);
    setExpandedDeedSlipId(activeSlip.id);
  }

  function handleMoveStructure(index, direction) {
    if (!activeSlip) return;
    updateSlip(activeSlip.id, (slip) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= slip.structure.length) return slip;
      const nextStructure = [...slip.structure];
      const [item] = nextStructure.splice(index, 1);
      nextStructure.splice(nextIndex, 0, item);
      return { ...slip, structure: nextStructure, updatedAt: new Date().toISOString() };
    });
  }

  function handleAddStructureStep() {
    if (!activeSlip) return;
    updateSlip(activeSlip.id, (slip) => ({
      ...slip,
      structure: [...slip.structure, "补一条新的结构步骤，检查页面里的整理态反馈。"],
      updatedAt: new Date().toISOString(),
    }));
    setToast("已插入一条结构步骤。");
  }

  function handleCycleCadence() {
    if (!activeSlip) return;
    updateSlip(activeSlip.id, (slip) => {
      const currentIndex = CADENCE_OPTIONS.indexOf(slip.cadence.schedule);
      const nextSchedule = CADENCE_OPTIONS[(currentIndex + 1 + CADENCE_OPTIONS.length) % CADENCE_OPTIONS.length];
      return {
        ...slip,
        cadence: {
          ...slip.cadence,
          schedule: nextSchedule,
        },
        updatedAt: new Date().toISOString(),
      };
    });
    setToast("已切换节律。");
  }

  function handleToggleCadence() {
    if (!activeSlip) return;
    updateSlip(activeSlip.id, (slip) => ({
      ...slip,
      cadence: {
        ...slip.cadence,
        enabled: !slip.cadence.enabled,
      },
      updatedAt: new Date().toISOString(),
    }));
    setToast(activeSlip.cadence.enabled ? "已停用节律。" : "已启用节律。");
  }

  function handlePromoteVersion(versionId) {
    if (!activeSlip || !activeDeed || activeDeed.status === "closed") return;
    updateDeedInSlip(activeSlip.id, activeDeed.id, (deed) => ({
      ...deed,
      selectedVersionId: versionId,
      feedback: "已改选",
      versions: deed.versions.map((item) => ({
        ...item,
        winning: item.id === versionId,
      })),
    }));
    setToast("已改选保留版本。");
  }

  function handleRunSlip() {
    if (!activeSlip || pendingRun) return;
    if (activeSlip.deed.status !== "closed") {
      handleOpenActiveDeed(activeSlip.deed.id);
      setToast("这张札已经有进行中的 deed，先进入它。");
      return;
    }

    const now = new Date().toISOString();
    const previousDeed = activeSlip.deed;
    const newDeedId = makeId("deed_mock");
    const newDeed = {
      id: newDeedId,
      status: "running",
      createdAt: now,
      updatedAt: now,
      feedback: "执行中",
      selectedVersionId: "v1",
      versions: [
        {
          id: "v1",
          name: "版本 A",
          note: "这一轮刚刚启动。",
          excerpt: "新的 deed 正在沿 DAG 推进。",
          winning: true,
        },
      ],
      files: [
        {
          id: makeId("file"),
          name: "running-draft.md",
          content: "## Running Draft\n\n这是一轮刚起的新 deed。",
        },
      ],
    };

    setDeedHistoryBySlipId((current) => ({
      ...current,
      [activeSlip.id]: [previousDeed, ...(current[activeSlip.id] || []).filter((item) => item.id !== previousDeed.id)],
    }));
    updateSlip(activeSlip.id, (slip) => ({
      ...slip,
      updatedAt: now,
      deed: newDeed,
    }));
    setDeedThreads((current) => ({
      ...current,
      [newDeedId]: [
        {
          message_id: makeId("msg"),
          role: "assistant",
          content: "新的 deed 已经起动。接下来只在 deed 页里继续这轮对话。",
          created_utc: now,
        },
      ],
    }));
    setReplyingSlipId(activeSlip.id);
    setPendingRun({
      slipId: activeSlip.id,
      deedId: newDeedId,
      prompt: composerValue.trim() || "把对象再压短一点",
    });
    setSelectedDeedId(newDeedId);
    setExpandedDeedSlipId(activeSlip.id);
    setToast("已起一轮假的 deed。");
  }

  function handleChangeCompareSide(side, versionId) {
    setCompareState((current) => ({ ...current, [side]: versionId }));
  }

  function handleMoveSlipInFolio(slipId, direction) {
    if (!activeFolio) return;
    updateFolio(activeFolio.id, (folio) => {
      const index = folio.slipIds.indexOf(slipId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= folio.slipIds.length) return folio;
      const next = [...folio.slipIds];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return { ...folio, slipIds: next };
    });
  }

  function handleDetachSlipFromFolio(slipId) {
    if (!activeFolio) return;
    updateFolio(activeFolio.id, (folio) => ({
      ...folio,
      slipIds: folio.slipIds.filter((item) => item !== slipId),
    }));
    setFolioEdges((current) => ({
      ...current,
      [activeFolio.id]: (current[activeFolio.id] || []).filter(([fromId, toId]) => fromId !== slipId && toId !== slipId),
    }));
    setPendingEdgeStartByFolio((current) => ({
      ...current,
      [activeFolio.id]: current[activeFolio.id] === slipId ? "" : current[activeFolio.id] || "",
    }));
    updateSlip(slipId, (slip) => ({
      ...slip,
      folioId: "",
      stance: "卷外",
      updatedAt: new Date().toISOString(),
    }));
    setFolioFocusById((current) => ({
      ...current,
      [activeFolio.id]: activeFolio.slipIds.find((item) => item !== slipId) || "",
    }));
    setToast("已把假札取出当前卷宗。");
  }

  function handleAttachSlipToFolio(slipId) {
    if (!activeFolio) return;
    setFolios((current) =>
      current.map((folio) => {
        if (folio.id === activeFolio.id) {
          return { ...folio, slipIds: [slipId, ...folio.slipIds.filter((item) => item !== slipId)] };
        }
        return { ...folio, slipIds: folio.slipIds.filter((item) => item !== slipId) };
      }),
    );
    updateSlip(slipId, (slip) => ({
      ...slip,
      folioId: activeFolio.id,
      stance: "在场",
      updatedAt: new Date().toISOString(),
    }));
    setFolioFocusById((current) => ({ ...current, [activeFolio.id]: slipId }));
    setToast("已把散札收入当前卷宗。");
  }

  function handleBoardSelectSlip(slipId) {
    if (!activeFolio) return;
    const pendingSlipId = pendingEdgeStartByFolio[activeFolio.id] || "";
    if (organizeMode && pendingSlipId) {
      if (pendingSlipId === slipId) {
        setPendingEdgeStartByFolio((current) => ({ ...current, [activeFolio.id]: "" }));
        setToast("已取消当前关系模式。");
        return;
      }
      toggleEdgeInFolio(activeFolio.id, pendingSlipId, slipId);
      setPendingEdgeStartByFolio((current) => ({ ...current, [activeFolio.id]: "" }));
      setFolioFocusById((current) => ({ ...current, [activeFolio.id]: slipId }));
      setToast("已切换两张札之间的关系。");
      return;
    }
    setFolioFocusById((current) => ({ ...current, [activeFolio.id]: slipId }));
  }

  function handleStartFolioLinking() {
    if (!activeFolio) return;
    if (!organizeMode) {
      setToast("先进入整理态，再改卷内连线。");
      return;
    }

    const pendingSlipId = pendingEdgeStartByFolio[activeFolio.id] || "";
    if (pendingSlipId) {
      setPendingEdgeStartByFolio((current) => ({ ...current, [activeFolio.id]: "" }));
      setToast("已取消当前关系模式。");
      return;
    }

    if (!focusedSlipId) {
      setToast("先在卷内视图里选中一张札，再建立关系。");
      return;
    }

    setPendingEdgeStartByFolio((current) => ({ ...current, [activeFolio.id]: focusedSlipId }));
    setToast("关系模式已开启。现在点另一张札，建立或取消它们之间的关系。");
  }

  function handleToggleFolioClock(slipId) {
    updateSlip(slipId, (slip) => ({
      ...slip,
      cadence: {
        ...slip.cadence,
        enabled: !slip.cadence.enabled,
      },
      updatedAt: new Date().toISOString(),
    }));
    if (activeFolio) {
      setFolioFocusById((current) => ({ ...current, [activeFolio.id]: slipId }));
    }
    const targetSlip = slips.find((item) => item.id === slipId);
    setToast(targetSlip?.cadence.enabled ? "已停用这张札的节律。" : "已启用这张札的节律。");
  }

  function handleAttachClick() {
    const currentIndex = ATTACHMENT_OPTIONS.indexOf(attachmentLabel);
    const nextAttachment = ATTACHMENT_OPTIONS[(currentIndex + 1 + ATTACHMENT_OPTIONS.length) % ATTACHMENT_OPTIONS.length];
    setAttachmentLabel(nextAttachment);
    setToast(`已挂上一份假材料：${nextAttachment}`);
  }

  function handleComposerChange(nextValue) {
    setComposerValue(nextValue);
    setComposerHistoryIndex(-1);
  }

  function rememberComposerPrompt(text) {
    setComposerHistory((current) => {
      if (!text || current[current.length - 1] === text) return current;
      return [...current, text];
    });
    setComposerHistoryIndex(-1);
  }

  function handleRecallComposerPrompt() {
    if (!composerHistory.length) return;
    const nextIndex = composerHistoryIndex === -1 ? composerHistory.length - 1 : Math.max(0, composerHistoryIndex - 1);
    setComposerHistoryIndex(nextIndex);
    setComposerValue(composerHistory[nextIndex] || "");
    if (expandedDeedSlipId && selectedDeedId) {
      setDeedDockFocused(true);
      return;
    }
    setDockFocused(true);
  }

  function handleSendMessage() {
    const text = composerValue.trim();
    if (!text) return;
    rememberComposerPrompt(text);

    if (activeDraft) {
      setDockFocused(true);
      const userMessage = {
        message_id: makeId("msg"),
        role: "user",
        content: text,
        created_utc: new Date().toISOString(),
      };
      const assistantMessage = {
        message_id: makeId("msg"),
        role: "assistant",
        content: buildAssistantReply("Draft", activeDraft.title, text, null),
        created_utc: new Date().toISOString(),
      };

      updateDraft(activeDraft.id, (draft) => ({
        ...draft,
        convergence: "方案继续收窄中",
        currentScheme: `${draft.currentScheme} ${shortText(text, 40)}`,
        messages: [...draft.messages, userMessage, assistantMessage],
      }));
      setComposerValue("");
      return;
    }

    if (activeFolio && !activeSlip) {
      setDockFocused(true);
      const userMessage = {
        message_id: makeId("msg"),
        role: "user",
        content: text,
        created_utc: new Date().toISOString(),
      };
      const assistantMessage = {
        message_id: makeId("msg"),
        role: "assistant",
        content: buildAssistantReply("Folio", activeFolio.title, text, null),
        created_utc: new Date().toISOString(),
      };
      setFolioThreads((current) => ({
        ...current,
        [activeFolio.id]: {
          messages: [...(current[activeFolio.id]?.messages || []), userMessage, assistantMessage],
        },
      }));
      setComposerValue("");
      return;
    }

    if (activeSlip && activeDeed) {
      if (activeDeed.status === "closed") return;
      setDeedDockFocused(true);

      const userMessage = {
        message_id: makeId("msg"),
        role: "user",
        content: text,
        created_utc: new Date().toISOString(),
      };
      const assistantMessage = {
        message_id: makeId("msg"),
        role: "assistant",
        content: buildAssistantReply("Deed", activeSlip.title, text, activeDeed.versions.find((item) => item.id === activeDeed.selectedVersionId)),
        created_utc: new Date().toISOString(),
      };

      appendDeedThread(activeDeed.id, userMessage);
      setComposerValue("");
      setReplyingSlipId(activeSlip.id);

      window.setTimeout(() => {
        appendDeedThread(activeDeed.id, assistantMessage);
        updateDeedInSlip(activeSlip.id, activeDeed.id, (deed) => ({
          ...deed,
          updatedAt: new Date().toISOString(),
        }));
        setReplyingSlipId("");
      }, 420);
      return;
    }

    if (!activeSlip) return;
    setDockFocused(true);

    const userMessage = {
      message_id: makeId("msg"),
      role: "user",
      content: text,
      created_utc: new Date().toISOString(),
    };
    const assistantMessage = {
      message_id: makeId("msg"),
      role: "assistant",
      content: buildAssistantReply("Slip", activeSlip.title, text, null),
      created_utc: new Date().toISOString(),
    };

    startTransition(() => {
      updateSlip(activeSlip.id, (slip) => ({
        ...slip,
        updatedAt: new Date().toISOString(),
        deed: {
          ...slip.deed,
          updatedAt: new Date().toISOString(),
        },
        messages: [...slip.messages, userMessage],
      }));
    });

    setComposerValue("");
    setReplyingSlipId(activeSlip.id);

    window.setTimeout(() => {
      startTransition(() => {
        updateSlip(activeSlip.id, (slip) => ({
          ...slip,
          updatedAt: new Date().toISOString(),
          messages: [...slip.messages, assistantMessage],
        }));
      });
      setReplyingSlipId("");
    }, 420);
  }

  function handleRetryMessage(message) {
    if (activeDraft) {
      const prompt = String(message.content || "").replace(/\s+/g, " ").trim();
      updateDraft(activeDraft.id, (draft) => ({
        ...draft,
        messages: [
          ...draft.messages,
          {
            message_id: makeId("msg"),
            role: "assistant",
            content: `我再收一遍这条草稿意图：${shortText(prompt, 52)}。先继续收窄，不急着成札。`,
            created_utc: new Date().toISOString(),
          },
        ],
      }));
      setToast("已在草稿里重跑这条消息。");
      return;
    }
    if (activeFolio && !activeSlip) {
      const prompt = String(message.content || "").replace(/\s+/g, " ").trim();
      setFolioThreads((current) => ({
        ...current,
        [activeFolio.id]: {
          messages: [
            ...(current[activeFolio.id]?.messages || []),
            {
              message_id: makeId("msg"),
              role: "assistant",
              content: `我再收一遍这条卷内安排：${shortText(prompt, 52)}。真正的结构变化仍然应该优先通过卷内视图完成。`,
              created_utc: new Date().toISOString(),
            },
          ],
        },
      }));
      setToast("已在卷内对话里重跑这条消息。");
      return;
    }
    if (activeSlip && activeDeed) {
      const prompt = String(message.content || "").replace(/\s+/g, " ").trim();
      appendDeedThread(activeDeed.id, {
        message_id: makeId("msg"),
        role: "assistant",
        content: `我再看一遍这轮 deed：${shortText(prompt, 48)}。`,
        created_utc: new Date().toISOString(),
      });
      setToast("已在当前 deed 里重跑这条消息。");
      return;
    }
    if (!activeSlip) return;
    const prompt = String(message.content || "").replace(/\s+/g, " ").trim();
    const nextMessage = {
      message_id: makeId("msg"),
      role: "assistant",
      content: `我重跑一遍这条：${shortText(prompt, 52)}。这次我会更偏向“先给判断，再给解释”的写法。`,
      created_utc: new Date().toISOString(),
    };
    updateSlip(activeSlip.id, (slip) => ({
      ...slip,
      updatedAt: new Date().toISOString(),
      messages: [...slip.messages, nextMessage],
    }));
    setToast("已在前端里重跑这条消息。");
  }

  function handleEditMessage(message) {
    handleComposerChange(String(message.content || ""));
    setToast("已把这条消息带回输入框。");
  }

  async function handleCopyMessage(message) {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(String(message.content || ""));
      }
    } catch (_error) {
      // Ignore clipboard failures in mock mode.
    }
    setCopiedMessageId(message.message_id || "");
    setToast("已复制这条消息。");
  }

  function handleRateMessage(message, reaction) {
    if (activeDraft) {
      updateDraft(activeDraft.id, (draft) => ({
        ...draft,
        messages: draft.messages.map((item) =>
          item.message_id === message.message_id
            ? {
                ...item,
                reaction: item.reaction === reaction ? "" : reaction,
              }
            : item,
        ),
      }));
      return;
    }
    if (activeFolio && !activeSlip) {
      setFolioThreads((current) => ({
        ...current,
        [activeFolio.id]: {
          messages: (current[activeFolio.id]?.messages || []).map((item) =>
            item.message_id === message.message_id
              ? {
                  ...item,
                  reaction: item.reaction === reaction ? "" : reaction,
                }
              : item,
          ),
        },
      }));
      return;
    }
    if (activeSlip && activeDeed) {
      setDeedThreads((current) => ({
        ...current,
        [activeDeed.id]: (current[activeDeed.id] || []).map((item) =>
          item.message_id === message.message_id
            ? {
                ...item,
                reaction: item.reaction === reaction ? "" : reaction,
              }
            : item,
        ),
      }));
      return;
    }
    if (!activeSlip) return;
    updateSlip(activeSlip.id, (slip) => ({
      ...slip,
      messages: slip.messages.map((item) =>
        item.message_id === message.message_id
          ? {
              ...item,
              reaction: item.reaction === reaction ? "" : reaction,
            }
          : item,
      ),
    }));
  }

  const activeFolioSlips = activeFolio
    ? activeFolio.slipIds
        .map((slipId) => slips.find((item) => item.id === slipId))
        .filter(Boolean)
    : [];
  const looseSlips = slips.filter((slip) => !slip.folioId);
  const activeFolioContent = activeFolio ? folioThreads[activeFolio.id] || { messages: [] } : null;
  const activeDeedMessages = activeDeed ? deedThreads[activeDeed.id] || [] : [];
  const dockMessages = activeDraft
    ? activeDraft.messages
    : activeFolio && !activeSlip
      ? activeFolioContent?.messages || []
      : activeSlip
        ? activeSlip.messages
        : [];
  const canReturnToFolio = Boolean(returnTarget?.kind === "folio" && returnTarget.id);
  const inputOwnerLabel = activeDraft
    ? "Draft"
    : activeFolio && !activeSlip
      ? "Folio"
      : activeDeed
        ? "Deed"
        : "Slip";
  const composerDisabled = Boolean(activeDeed && activeDeed.status === "closed");

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key !== "Escape") return;
      if (expandedDeedSlipId) {
        setExpandedDeedSlipId("");
        setSelectedDeedId("");
        setCompareState((current) => ({ ...current, open: false }));
        return;
      }
      if (expandedFolioId) {
        setExpandedFolioId("");
        return;
      }
      if (expandedMoveSlipId) {
        setExpandedMoveSlipId("");
        return;
      }
      if (canReturnToFolio) {
        handleBackToReturnTarget();
        return;
      }
      if (deedDockFocused) {
        setDeedDockFocused(false);
        return;
      }
      if (dockFocused) {
        setDockFocused(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canReturnToFolio, deedDockFocused, dockFocused, expandedDeedSlipId, expandedFolioId, expandedMoveSlipId, handleBackToReturnTarget]);

  return (
    <div className="flex h-full overflow-hidden bg-[#F5F5F0] text-[#1a1a18]">
      <MockSidebar
        drafts={deskDrafts}
        folios={filteredFolios}
        slips={filteredLooseSlips}
        selectedTarget={selectedTarget}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onSelectDraft={(draftId) => setSelectedTarget({ kind: "draft", id: draftId })}
        onSelectFolio={(folioId) => {
          setReturnTarget(null);
          setExpandedFolioId("");
          setExpandedMoveSlipId("");
          setSelectedTarget({ kind: "folio", id: folioId });
        }}
        onSelectSlip={selectSlipDirect}
        onCreateSlip={() => handleCreateDraft("")}
        onShuffle={handleShuffle}
      />

      <main className="relative min-w-0 flex flex-1 flex-col overflow-hidden">
        <div
          className="min-h-0 flex-1 overflow-y-auto pb-40"
          onPointerDownCapture={() => setDockFocused(false)}
          onMouseDown={(event) => {
            if (canReturnToFolio && event.target === event.currentTarget) {
              handleBackToReturnTarget();
            }
          }}
        >
          <div className="mx-auto flex w-full max-w-[58.5rem] flex-col px-5 pb-12 pt-10">
            {selectedTarget.kind === "draft" && activeDraft ? (
              <DraftWorkspace
                draft={activeDraft}
                targetFolio={currentFolio}
                onCrystallize={handleCrystallizeDraft}
                onAbandon={handleAbandonDraft}
              />
            ) : selectedTarget.kind === "folio" && activeFolio ? (
              <FolioWorkspace
                folio={activeFolio}
                slips={activeFolioSlips}
                looseSlips={looseSlips}
                content={activeFolioContent}
                edges={folioEdges[activeFolio.id] || []}
                expanded={expandedFolioId === activeFolio.id}
                organizeMode={organizeMode}
                onOpenExpanded={() => setExpandedFolioId(activeFolio.id)}
                onCloseExpanded={() => setExpandedFolioId("")}
                onToggleOrganize={() =>
                  setOrganizeMode((current) => {
                    const next = !current;
                    return next;
                  })
                }
                onOpenSlip={(slipId) =>
                  openSlipFromFolio(slipId, {
                    folioId: activeFolio.id,
                    expanded: expandedFolioId === activeFolio.id,
                  })
                }
                onToggleClock={handleToggleFolioClock}
                onMoveSlip={handleMoveSlipInFolio}
                onDetachSlip={handleDetachSlipFromFolio}
                onAttachSlip={handleAttachSlipToFolio}
                onCreateSlip={() => handleCreateSlip({ folioId: activeFolio.id, keepFocusOnFolio: true })}
                onRetryMessage={handleRetryMessage}
                onEditMessage={handleEditMessage}
                onCopyMessage={handleCopyMessage}
                onRateMessage={handleRateMessage}
                copiedMessageId={copiedMessageId}
              />
            ) : activeSlip ? (
              <>
                <SlipWorkspace
                  slip={activeSlip}
                  folio={currentFolio}
                  deeds={activeSlipDeeds}
                  activeDeedId={selectedDeedId}
                  structureMode={structureMode}
                  onRun={handleRunSlip}
                  onOpenDeed={handleOpenActiveDeed}
                  onToggleStructureMode={() => setStructureMode((current) => !current)}
                  onMoveStructure={handleMoveStructure}
                  onAddStructureStep={handleAddStructureStep}
                  onCycleCadence={handleCycleCadence}
                  onToggleCadence={handleToggleCadence}
                  onOpenMoveExpanded={() => setExpandedMoveSlipId(activeSlip.id)}
                />

                {expandedMoveSlipId === activeSlip.id ? (
                  <MoveGraphExpandedView
                    slip={activeSlip}
                    editMode={structureMode}
                    onClose={() => setExpandedMoveSlipId("")}
                    onToggleEdit={() => setStructureMode((current) => !current)}
                    onMoveStep={handleMoveStructure}
                    onAddStep={handleAddStructureStep}
                    onCycleCadence={handleCycleCadence}
                    onToggleCadence={handleToggleCadence}
                  />
                ) : null}

                {expandedDeedSlipId === activeSlip.id && activeDeed ? (
                  <DeedExpandedView
                    slip={activeSlip}
                    deed={activeDeed}
                    messages={activeDeedMessages}
                    compareState={compareState}
                    onBack={() => {
                      setExpandedDeedSlipId("");
                      setSelectedDeedId("");
                      setCompareState((current) => ({ ...current, open: false }));
                    }}
                    onToggleCompare={handleToggleCompare}
                    onPromoteVersion={handlePromoteVersion}
                    onChangeCompareSide={handleChangeCompareSide}
                    onCloseCompare={() => setCompareState((current) => ({ ...current, open: false }))}
                    composerValue={composerValue}
                    onComposerChange={handleComposerChange}
                    onComposerSubmit={handleSendMessage}
                    onComposerHistoryUp={handleRecallComposerPrompt}
                    composerDisabled={composerDisabled}
                    composerLoading={Boolean(replyingSlipId && activeSlip && replyingSlipId === activeSlip.id)}
                    attachmentLabel={attachmentLabel}
                    onAttachClick={handleAttachClick}
                    onRetryMessage={handleRetryMessage}
                    onEditMessage={handleEditMessage}
                    onCopyMessage={handleCopyMessage}
                    onRateMessage={handleRateMessage}
                    copiedMessageId={copiedMessageId}
                    dockFocused={deedDockFocused}
                    onDockFocusChange={setDeedDockFocused}
                  />
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {activeDraft || activeFolio || activeSlip ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
            <ConversationDock
              ownerLabel={inputOwnerLabel}
              focused={dockFocused}
              onFocusChange={setDockFocused}
              messages={dockMessages}
              composerValue={composerValue}
              onComposerChange={handleComposerChange}
              onComposerSubmit={handleSendMessage}
              onComposerHistoryUp={handleRecallComposerPrompt}
              composerDisabled={composerDisabled}
              composerLoading={Boolean(replyingSlipId && activeSlip && replyingSlipId === activeSlip.id)}
              attachmentLabel={attachmentLabel}
              onAttachClick={handleAttachClick}
              onRetryMessage={handleRetryMessage}
              onEditMessage={handleEditMessage}
              onCopyMessage={handleCopyMessage}
              onRateMessage={handleRateMessage}
              copiedMessageId={copiedMessageId}
            />
          </div>
        ) : null}
      </main>

      {toast ? (
        <div className="pointer-events-none fixed right-6 top-6 z-50 rounded-2xl border border-[rgba(0,0,0,0.08)] bg-white px-4 py-3 text-sm text-[#1a1a18] shadow-claude">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
