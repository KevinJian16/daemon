#!/usr/bin/env bash
# Clean residual directories from ~/.openclaw/agents/
#
# Current canonical agents (10 total):
#   L1 scene agents: copilot, instructor, navigator, autopilot
#   L2 exec agents:  researcher, engineer, writer, reviewer, publisher, admin
#
# Directories found in ~/.openclaw/agents/ that do NOT match the canonical list
# are considered residuals from old architecture and should be removed.
#
# Usage:
#   bash scripts/clean_openclaw_residual.sh          # dry-run (shows what would be removed)
#   bash scripts/clean_openclaw_residual.sh --apply  # actually remove residuals

set -euo pipefail

AGENTS_DIR="${OPENCLAW_HOME:-$HOME/.openclaw}/agents"

# Canonical agent IDs
CANONICAL_AGENTS=(
    copilot
    instructor
    navigator
    autopilot
    researcher
    engineer
    writer
    reviewer
    publisher
    admin
)

DRY_RUN=true
if [[ "${1:-}" == "--apply" ]]; then
    DRY_RUN=false
fi

if [[ ! -d "$AGENTS_DIR" ]]; then
    echo "Agents directory not found: $AGENTS_DIR"
    exit 0
fi

echo "Scanning: $AGENTS_DIR"
echo ""

# Build set of canonical names for fast lookup
declare -A canonical_set
for agent in "${CANONICAL_AGENTS[@]}"; do
    canonical_set["$agent"]=1
done

residuals=()
while IFS= read -r -d '' entry; do
    dir_name=$(basename "$entry")
    if [[ -z "${canonical_set[$dir_name]+_}" ]]; then
        residuals+=("$entry")
    fi
done < <(find "$AGENTS_DIR" -mindepth 1 -maxdepth 1 -type d -print0)

if [[ ${#residuals[@]} -eq 0 ]]; then
    echo "No residual directories found. Nothing to clean."
    exit 0
fi

echo "Residual directories (not in canonical agent list):"
for dir in "${residuals[@]}"; do
    echo "  $dir"
done
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "DRY RUN — no changes made."
    echo "Run with --apply to remove the above directories."
else
    echo "Removing residual directories..."
    for dir in "${residuals[@]}"; do
        rm -rf "$dir"
        echo "  Removed: $dir"
    done
    echo "Done."
fi
