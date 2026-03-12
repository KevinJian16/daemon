import { ArrowDownLeft, ArrowUpRight, Clock3, FolderOpen, Search } from "lucide-react";
import { cx } from "../lib/format";

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
  folioCard:
    "0 1.5px 0 rgba(255,255,255,0.95) inset, 0 -1px 0 rgba(41,41,41,0.04) inset, 0 26px 46px rgba(41,41,41,0.09), 0 10px 18px rgba(41,41,41,0.05)",
};

function shortNodeLabel(label, fallback, index) {
  const text = String(label || fallback || `Move ${index + 1}`).trim();
  if (text.length <= 26) return text;
  return `${text.slice(0, 25)}…`;
}

function normalizedDag(dag) {
  const rawNodes = Array.isArray(dag?.nodes) ? dag.nodes : [];
  const rawEdges = Array.isArray(dag?.edges) ? dag.edges : [];
  const nodes = rawNodes
    .filter((node) => node && typeof node === "object")
    .map((node, index) => ({
      id: String(node.id || `move_${index + 1}`),
      label: shortNodeLabel(node.label, node.title, index),
      agent: String(node.agent || ""),
      status: String(node.status || "pending").toLowerCase(),
    }));
  const idSet = new Set(nodes.map((node) => node.id));
  const edges = rawEdges
    .filter((edge) => edge && typeof edge === "object")
    .map((edge) => ({
      from: String(edge.from || ""),
      to: String(edge.to || ""),
    }))
    .filter((edge) => edge.from && edge.to && idSet.has(edge.from) && idSet.has(edge.to));
  return { nodes, edges };
}

function dagLevels(dag) {
  const incoming = new Map();
  const outgoing = new Map();
  dag.nodes.forEach((node) => {
    incoming.set(node.id, 0);
    outgoing.set(node.id, []);
  });
  dag.edges.forEach((edge) => {
    incoming.set(edge.to, (incoming.get(edge.to) || 0) + 1);
    outgoing.set(edge.from, [...(outgoing.get(edge.from) || []), edge.to]);
  });

  const queue = dag.nodes.filter((node) => (incoming.get(node.id) || 0) === 0).map((node) => node.id);
  const levels = new Map(queue.map((id) => [id, 0]));
  const visited = new Set(queue);

  while (queue.length) {
    const current = queue.shift();
    const currentLevel = levels.get(current) || 0;
    for (const next of outgoing.get(current) || []) {
      const nextLevel = Math.max(levels.get(next) || 0, currentLevel + 1);
      levels.set(next, nextLevel);
      incoming.set(next, Math.max(0, (incoming.get(next) || 0) - 1));
      if ((incoming.get(next) || 0) === 0 && !visited.has(next)) {
        queue.push(next);
        visited.add(next);
      }
    }
  }

  dag.nodes.forEach((node, index) => {
    if (!levels.has(node.id)) {
      levels.set(node.id, Math.min(index, dag.nodes.length - 1));
    }
  });
  return levels;
}

function layoutDag(dag, compact = false) {
  const levels = dagLevels(dag);
  const grouped = new Map();
  dag.nodes.forEach((node) => {
    const level = levels.get(node.id) || 0;
    grouped.set(level, [...(grouped.get(level) || []), node]);
  });
  const levelKeys = [...grouped.keys()].sort((left, right) => left - right);
  const cardWidth = compact ? 156 : 180;
  const cardHeight = compact ? 70 : 86;
  const stepX = compact ? 208 : 232;
  const paddingX = compact ? 28 : 34;
  const paddingY = compact ? 26 : 34;
  const verticalSpace = compact ? 112 : 138;
  const positioned = [];

  levelKeys.forEach((level) => {
    const group = grouped.get(level) || [];
    const totalHeight = (group.length - 1) * verticalSpace;
    group.forEach((node, index) => {
      positioned.push({
        ...node,
        x: paddingX + level * stepX,
        y: paddingY + 92 - totalHeight / 2 + index * verticalSpace,
      });
    });
  });

  const width = Math.max(
    compact ? 640 : 760,
    positioned.reduce((max, node) => Math.max(max, node.x + cardWidth + paddingX), compact ? 640 : 760),
  );
  const height = Math.max(
    compact ? 250 : 292,
    positioned.reduce((max, node) => Math.max(max, node.y + cardHeight + paddingY), compact ? 250 : 292),
  );
  return { width, height, cardWidth, cardHeight, nodes: positioned, edges: dag.edges };
}

function deedNodeState(nodes, runtimeStatuses = {}) {
  const byId = new Map(nodes.map((node) => [node.id, String(runtimeStatuses[node.id] || node.status || "pending").toLowerCase()]));
  const activeNode = nodes.find((node) => byId.get(node.id) === "running");
  const fallbackActive = nodes.find((node) => byId.get(node.id) === "failed") || nodes[nodes.length - 1] || null;
  const activeId = activeNode?.id || fallbackActive?.id || "";
  return { byId, activeId };
}

function deedNodeTone(state, deedStatus, nodeId, activeId) {
  if (state === "failed") return { border: "#8B3C2F", text: "#8B3C2F", active: false, visited: false, muted: false };
  if (nodeId === activeId && deedStatus === "running") {
    return { border: GRAPH_TOKENS.activeTone, text: "#FFF9F3", active: true, visited: false, muted: false };
  }
  if (state === "completed" || state === "succeeded" || state === "closed") {
    return { border: GRAPH_TOKENS.visitedTone, text: GRAPH_TOKENS.textPrimary, active: false, visited: true, muted: false };
  }
  return { border: GRAPH_TOKENS.borderDefault, text: GRAPH_TOKENS.textPrimary, active: false, visited: false, muted: deedStatus === "running" };
}

export function MoveGraphCanvas({
  dag,
  compact = false,
  className = "",
  mode = "structure",
  runtimeStatuses = {},
  deedStatus = "closed",
  testId = "move-graph",
}) {
  const normalized = normalizedDag(dag);
  const graph = layoutDag(normalized.nodes.length ? normalized : { nodes: [{ id: "move_1", label: "尚未定义", status: "pending" }], edges: [] }, compact);
  const isDeed = mode === "deed";
  const boardWidth = graph.width;
  const boardHeight = graph.height;
  const { byId, activeId } = deedNodeState(graph.nodes, runtimeStatuses);

  function centerOf(node) {
    return {
      x: node.x + graph.cardWidth / 2,
      y: node.y + graph.cardHeight / 2,
    };
  }

  return (
    <div
      data-testid={testId}
      className={cx("overflow-x-auto rounded-[1.6rem]", className)}
      style={{ background: GRAPH_TOKENS.canvas, boxShadow: "inset 0 0 0 1px rgba(41,41,41,0.06)" }}
    >
      <div className="relative" style={{ width: `${boardWidth}px`, height: `${boardHeight}px` }}>
        {!isDeed ? (
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(173,173,173,0.14)_1px,transparent_0)] bg-[length:18px_18px] opacity-[0.08]" />
        ) : null}

        <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${boardWidth} ${boardHeight}`} preserveAspectRatio="none">
          {graph.edges.map((edge) => {
            const fromNode = graph.nodes.find((node) => node.id === edge.from);
            const toNode = graph.nodes.find((node) => node.id === edge.to);
            if (!fromNode || !toNode) return null;
            const start = centerOf(fromNode);
            const end = centerOf(toNode);
            const midX = (start.x + end.x) / 2;
            const activeEdge = isDeed && deedStatus === "running" && edge.to === activeId;
            const visited = isDeed && ["completed", "succeeded", "closed"].includes(byId.get(edge.to));
            const pathDefinition = `M ${start.x} ${start.y} C ${midX} ${start.y}, ${midX} ${end.y}, ${end.x} ${end.y}`;
            return (
              <g key={`${edge.from}-${edge.to}`}>
                <path
                  d={pathDefinition}
                  fill="none"
                  stroke={isDeed ? (visited ? GRAPH_TOKENS.visitedTone : "rgba(205,205,205,0.48)") : GRAPH_TOKENS.lineDefault}
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
          const state = byId.get(node.id) || "pending";
          const tone = deedNodeTone(state, deedStatus, node.id, activeId);
          const background = tone.active
            ? `linear-gradient(180deg, rgba(255,255,255,0.24) 0px, rgba(255,255,255,0.08) 14px, rgba(255,255,255,0) 30px), linear-gradient(180deg, rgba(255,255,255,0) 52%, rgba(120,53,25,0.12) 100%), ${GRAPH_TOKENS.activeTone}`
            : `linear-gradient(180deg, rgba(255,255,255,0.86) 0px, rgba(255,255,255,0.34) 14px, rgba(255,255,255,0) 28px), linear-gradient(180deg, rgba(255,255,255,0) 54%, rgba(41,41,41,0.03) 100%), ${GRAPH_TOKENS.nodeSurface}`;
          return (
            <div
              key={node.id}
              data-testid={`${testId}-node-${node.id}`}
              className={cx(
                "absolute border transition duration-150",
                compact ? "rounded-[1.55rem] px-[1rem] py-[1rem]" : "rounded-[1.75rem] px-[1.08rem] py-[1.08rem]",
                tone.active ? "portal-flow-node" : "",
              )}
              style={{
                left: `${node.x}px`,
                top: `${node.y}px`,
                width: `${graph.cardWidth}px`,
                minHeight: `${graph.cardHeight}px`,
                background,
                color: tone.text,
                opacity: tone.muted && !tone.active && !tone.visited ? 0.52 : 1,
                borderColor: tone.active ? tone.border : "rgba(173,173,173,0.72)",
                boxShadow: tone.active ? GRAPH_RELIEF.activeNode : GRAPH_RELIEF.node,
              }}
            >
              <div className="flex items-start gap-2.5">
                {isDeed ? (
                  <span
                    className={cx(
                      "mt-[0.28rem] inline-flex h-2.5 w-2.5 shrink-0 rounded-full",
                      tone.active ? "bg-[#ffd6bf] animate-pulse" : tone.visited ? "bg-[#686868]" : state === "failed" ? "bg-[#8B3C2F]" : "bg-[#ADADAD]",
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
                  {node.label}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function slipStatusDot(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "bg-[#ae5630]";
  if (key === "settling") return "bg-[#8a4a26]";
  if (key === "closed") return "bg-[#686868]";
  if (key === "failed") return "bg-[#8b3c2f]";
  return "bg-[#adadad]";
}

export function FolioBoard({
  slips,
  writs,
  compact = false,
  onSelectSlip,
  onDetailClick = null,
  onToggleClock = null,
  organizing = false,
  draggingSlipSlug = "",
  dropTargetSlug = "",
  boardDropActive = false,
  onCardDragStart = null,
  onCardDragEnd = null,
  onCardDragOver = null,
  onCardDrop = null,
  onBoardDragOver = null,
  onBoardDragLeave = null,
  onBoardDrop = null,
  testId = "folio-board",
}) {
  const cardWidth = compact ? 148 : 192;
  const cardHeight = compact ? 92 : 142;
  const gapX = compact ? 28 : 48;
  const gapY = organizing ? (compact ? 26 : 42) : compact ? 34 : 68;
  const boardPadding = compact ? 32 : 48;
  const floatingRows = compact ? 2 : slips.length <= 6 ? 2 : 3;
  const gridColumns = Math.max(1, compact ? Math.min(3, slips.length || 1) : Math.min(4, slips.length || 1));
  const gridRows = Math.max(1, Math.ceil(slips.length / gridColumns));
  const spreadColumns = Math.max(1, Math.min(compact ? 3 : 4, slips.length || 1));
  const shouldSpread = !organizing && slips.length > 0 && slips.length <= (compact ? 3 : 4);
  const rawNodes = slips.map((slip, index) => {
    if (organizing) {
      const column = index % gridColumns;
      const row = Math.floor(index / gridColumns);
      return {
        slip,
        left: boardPadding + column * (cardWidth + gapX),
        top: (compact ? 32 : 46) + row * (cardHeight + gapY),
      };
    }

    if (shouldSpread) {
      const column = index % spreadColumns;
      const row = Math.floor(index / spreadColumns);
      const staggerY = compact ? (row === 0 ? 0 : 18) : row === 0 ? 0 : 26;
      return {
        slip,
        left: boardPadding + column * (cardWidth + gapX + (compact ? 26 : 34)),
        top: (compact ? 82 : 116) + staggerY,
      };
    }

    const column = Math.floor(index / floatingRows);
    const row = index % floatingRows;
    const offsetX = compact ? (row % 2 === 1 ? 10 : 0) : row === 1 ? 18 : row === 2 ? 6 : 0;
    return {
      slip,
      left: boardPadding + column * (cardWidth + gapX) + offsetX,
      top: (compact ? 28 : 40) + row * (cardHeight + gapY),
    };
  });
  const initialBoardWidth = Math.max(
    compact ? 600 : 860,
    rawNodes.reduce((current, node) => Math.max(current, node.left + cardWidth + boardPadding), 0),
  );
  const clusterLeft = rawNodes.length ? Math.min(...rawNodes.map((node) => node.left)) : boardPadding;
  const clusterRight = rawNodes.length ? Math.max(...rawNodes.map((node) => node.left + cardWidth)) : boardPadding;
  const centerOffset = Math.max(0, (initialBoardWidth - (clusterRight - clusterLeft)) / 2 - clusterLeft);
  const nodes = rawNodes.map((node) => ({ ...node, left: node.left + centerOffset }));
  const visibleRows = organizing ? gridRows : shouldSpread ? Math.max(1, Math.ceil(slips.length / spreadColumns)) : floatingRows;
  const boardWidth = Math.max(compact ? 600 : 860, nodes.reduce((current, node) => Math.max(current, node.left + cardWidth + boardPadding), 0));
  const boardHeight = Math.max(compact ? 248 : 430, (organizing ? (compact ? 32 : 46) : compact ? 28 : 40) + visibleRows * (cardHeight + gapY));
  const relationStats = slips.reduce((map, slip) => {
    map[String(slip?.id || "")] = { incoming: 0, outgoing: 0 };
    return map;
  }, {});

  (writs || []).forEach((writ) => {
    const sourceId = String(writ?.source_slip_id || "");
    const targetId = String(writ?.target_slip_id || "");
    if (relationStats[sourceId]) relationStats[sourceId].outgoing += 1;
    if (relationStats[targetId]) relationStats[targetId].incoming += 1;
  });

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
              data-testid={`${testId}-detail`}
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
          data-testid={testId}
          className="relative min-w-full rounded-[1.6rem]"
          onDragOver={(event) => onBoardDragOver?.(event)}
          onDragLeave={(event) => onBoardDragLeave?.(event)}
          onDrop={(event) => onBoardDrop?.(event)}
          style={{
            width: `${boardWidth}px`,
            height: `${boardHeight}px`,
            background: GRAPH_TOKENS.canvas,
            boxShadow: boardDropActive
              ? "inset 0 0 0 1px rgba(174,86,48,0.24), inset 0 0 0 8px rgba(174,86,48,0.04)"
              : "inset 0 0 0 1px rgba(41,41,41,0.06)",
          }}
        >
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(173,173,173,0.14)_1px,transparent_0)] bg-[length:22px_22px] opacity-[0.08]" />
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${boardWidth} ${boardHeight}`} preserveAspectRatio="none">
            <defs>
              <marker
                id={`${testId}-arrow`}
                markerWidth="8"
                markerHeight="8"
                refX="6"
                refY="4"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M 0 0 L 8 4 L 0 8 z" fill={GRAPH_TOKENS.visitedTone} opacity="0.72" />
              </marker>
            </defs>
            {(writs || []).map((writ) => {
              const fromNode = nodes.find((node) => node.slip.id === writ.source_slip_id);
              const toNode = nodes.find((node) => node.slip.id === writ.target_slip_id);
              if (!fromNode || !toNode) return null;
              const start = nodeCenter(fromNode);
              const end = nodeCenter(toNode);
              const leftToRight = end.x >= start.x;
              const startX = leftToRight ? start.x + cardWidth / 2 - 14 : start.x - cardWidth / 2 + 14;
              const endX = leftToRight ? end.x - cardWidth / 2 + 18 : end.x + cardWidth / 2 - 18;
              const sameRow = Math.abs(end.y - start.y) < (compact ? 14 : 22);
              const distanceX = Math.abs(endX - startX);
              const curve = Math.max(18, Math.min(distanceX * 0.34, compact ? 42 : 62));
              const controlStartX = leftToRight ? startX + curve : startX - curve;
              const controlEndX = leftToRight ? endX - curve : endX + curve;
              const controlStartY = organizing ? start.y : start.y;
              const controlEndY = organizing ? end.y : end.y;
              const pathDefinition = sameRow
                ? `M ${startX} ${start.y} L ${endX} ${end.y}`
                : `M ${startX} ${start.y} C ${controlStartX} ${controlStartY}, ${controlEndX} ${controlEndY}, ${endX} ${end.y}`;
              return (
                <g key={writ.id}>
                  <path
                    d={pathDefinition}
                    fill="none"
                    stroke={GRAPH_TOKENS.visitedTone}
                    strokeWidth={compact ? "1.4" : "1.9"}
                    strokeLinecap="round"
                    strokeOpacity={compact ? 0.62 : 0.72}
                    markerEnd={`url(#${testId}-arrow)`}
                  />
                  <circle cx={startX} cy={start.y} r={compact ? "2.2" : "2.6"} fill={GRAPH_TOKENS.visitedTone} opacity="0.56" />
                </g>
              );
            })}
          </svg>

          {nodes.map((node) => {
            const cadenceActive = Boolean(node.slip?.cadence?.active);
            return (
              <div
                key={node.slip.id}
                data-testid={`${testId}-card-${node.slip.slug}`}
                role="button"
                tabIndex={0}
                draggable={organizing}
                onClick={() => {
                  if (organizing) return;
                  onSelectSlip?.(node.slip);
                }}
                onDragStart={(event) => onCardDragStart?.(event, node.slip)}
                onDragEnd={() => onCardDragEnd?.(node.slip)}
                onDragOver={(event) => {
                  if (!organizing) return;
                  event.preventDefault();
                  onCardDragOver?.(event, node.slip);
                }}
                onDrop={(event) => {
                  if (!organizing) return;
                  event.preventDefault();
                  onCardDrop?.(event, node.slip);
                }}
                onKeyDown={(event) => {
                  if (organizing) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectSlip?.(node.slip);
                  }
                }}
                className={cx(
                  "absolute border px-5 text-left transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] hover:-translate-y-[1px]",
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
                  boxShadow:
                    dropTargetSlug === node.slip.slug
                      ? "0 0 0 1px rgba(174,86,48,0.26), 0 28px 46px rgba(41,41,41,0.1), 0 1.5px 0 rgba(255,255,255,0.95) inset, 0 -1px 0 rgba(41,41,41,0.04) inset"
                      : GRAPH_RELIEF.folioCard,
                  opacity: draggingSlipSlug === node.slip.slug ? 0.42 : 1,
                  cursor: organizing ? "grab" : "pointer",
                }}
              >
                <div className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <span
                      className="inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2"
                      style={{
                        background: "rgba(255,255,255,0.76)",
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.86), 0 3px 6px rgba(41,41,41,0.04)",
                      }}
                    >
                      <span className={cx("inline-flex h-2.5 w-2.5 shrink-0 rounded-full", slipStatusDot(node.slip.deed?.status))} />
                    </span>

                    {onToggleClock ? (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          onToggleClock(node.slip);
                        }}
                        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition hover:bg-white"
                        style={{
                          borderColor: "rgba(41,41,41,0.08)",
                          background: cadenceActive ? "rgba(174,86,48,0.08)" : "rgba(255,255,255,0.78)",
                          color: cadenceActive ? GRAPH_TOKENS.activeTone : GRAPH_TOKENS.visitedTone,
                          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.84)",
                        }}
                        title="切换节律"
                      >
                        <Clock3 width={11} height={11} />
                      </button>
                    ) : (
                      <span
                        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border"
                        style={{
                          borderColor: "rgba(41,41,41,0.08)",
                          background: cadenceActive ? "rgba(174,86,48,0.08)" : "rgba(255,255,255,0.78)",
                          color: cadenceActive ? GRAPH_TOKENS.activeTone : GRAPH_TOKENS.visitedTone,
                          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.84)",
                        }}
                      >
                        <Clock3 width={11} height={11} />
                      </span>
                    )}
                  </div>

                  <div className="mt-3 min-w-0">
                    <div className={compact ? "line-clamp-2 text-[13.2px] font-medium leading-[1.16] text-[#292929]" : "line-clamp-2 text-[14px] font-medium leading-[1.16] text-[#292929]"}>
                      {node.slip.title}
                    </div>
                  </div>

                  <div className="mt-auto pt-3">
                    <div className="flex items-center justify-between gap-2 border-t border-[rgba(41,41,41,0.06)] pt-2.5">
                      <div className="flex items-center gap-1.5 text-[#7a766f]">
                        {relationStats[String(node.slip.id || "")]?.incoming ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-[rgba(255,255,255,0.72)] px-2 py-1 text-[10px]">
                            <ArrowDownLeft width={10} height={10} />
                            <span>{relationStats[String(node.slip.id || "")].incoming}</span>
                          </span>
                        ) : null}
                        {relationStats[String(node.slip.id || "")]?.outgoing ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-[rgba(255,255,255,0.72)] px-2 py-1 text-[10px]">
                            <ArrowUpRight width={10} height={10} />
                            <span>{relationStats[String(node.slip.id || "")].outgoing}</span>
                          </span>
                        ) : null}
                      </div>
                      <span className="inline-flex h-1.5 w-1.5 rounded-full bg-[rgba(41,41,41,0.12)]" />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function graphNodeStatusMapFromDag(dag) {
  const nodes = Array.isArray(dag?.nodes) ? dag.nodes : [];
  return Object.fromEntries(nodes.map((node) => [String(node.id || ""), String(node.status || "pending").toLowerCase()]));
}
