#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/post-init-check.sh — verify init-plugin.sh left no ``hello``
# residuals behind.
#
# init-plugin.sh runs identifier-scoped seds. A handful of patterns slip
# past those (regex limitations on multi-segment paths, wildcards,
# single-quoted TS strings, frontend file extensions). This script does
# a final grep pass and reports anything it finds, so the user catches
# residuals before the first commit.
#
# Auto-invoked by ``init-plugin.sh`` at the end. You can also run it
# manually any time:
#
#     ./scripts/post-init-check.sh <namespace>
#
# Exit codes:
#   0 — clean (no residuals)
#   1 — residuals found (stdout lists them)
#   2 — usage error
# ---------------------------------------------------------------------------

set -uo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <namespace>" >&2
    exit 2
fi

NAMESPACE="$1"
RC=0

# Excludes:
#   - .git/ ; node_modules/ ; build artefacts ; this script itself
#   - the init-plugin.sh comment block (doc literally references "hello")
#   - markdown prose files (where the English word "hello" is allowed)
EXCLUDES=(
    "--exclude-dir=.git"
    "--exclude-dir=node_modules"
    "--exclude-dir=__pycache__"
    "--exclude-dir=.pytest_cache"
    "--exclude-dir=.ruff_cache"
    "--exclude-dir=dist"
    "--exclude-dir=build"
    "--exclude=*.lock"
    "--exclude=package-lock.json"
    "--exclude=post-init-check.sh"
)

echo "Auditing for 'hello' residuals (namespace=${NAMESPACE})..."

# Code/config files — any 'hello' here is suspicious.
HITS=$(grep -rn "${EXCLUDES[@]}" \
    --include="*.py" --include="*.toml" --include="*.json" \
    --include="*.sql" --include="*.yml" --include="*.yaml" \
    --include="*.ts" --include="*.tsx" \
    -e 'hello' . 2>/dev/null | \
    grep -v '^[^:]*\.md:' || true)

if [ -n "$HITS" ]; then
    echo ""
    echo "[!] Found 'hello' residuals in code/config files:"
    echo "$HITS"
    echo ""
    echo "Review each — most are init-plugin.sh blind spots:"
    echo "  * pyproject.toml entry-point key ([project.entry-points.\"piilot.plugins\"])"
    echo "  * permissions wildcards (\"hello.*\" → \"${NAMESPACE}.*\")"
    echo "  * frontend/src/*.ts / *.tsx single-quoted strings"
    echo "  * migration filenames (002_hello_*.sql)"
    RC=1
fi

# Migration filenames (residual #6) — checked separately because the
# grep above only sees file *content*, not file *names*.
MIG_HITS=$(find . -type f -name "*hello*.sql" -not -path "./.git/*" 2>/dev/null || true)
if [ -n "$MIG_HITS" ]; then
    echo ""
    echo "[!] Migration filenames still contain 'hello':"
    echo "$MIG_HITS"
    echo ""
    echo "Rename them with: git mv <old> <new>  (replace 'hello' with '${NAMESPACE}')"
    RC=1
fi

# Version drift — pyproject.toml / package.json should be 0.1.0 on first
# init. Older template versions (0.3.0, 0.4.0) leaking through are a
# strong signal init-plugin.sh's reset step didn't run.
PYP_VERSION=$(grep -E '^version = "[0-9]+\.[0-9]+\.[0-9]+"' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
if [ -n "$PYP_VERSION" ] && [ "$PYP_VERSION" != "0.1.0" ]; then
    echo ""
    echo "[!] pyproject.toml version is ${PYP_VERSION} — expected 0.1.0 for a fresh scaffold."
    RC=1
fi

if [ -f "frontend/package.json" ]; then
    NPM_VERSION=$(grep -E '"version": "[0-9]+\.[0-9]+\.[0-9]+"' frontend/package.json | head -1 | sed -E 's/.*"([^"]+)".*/\1/' | tr -d ' ')
    if [ -n "$NPM_VERSION" ] && [ "$NPM_VERSION" != "0.1.0" ]; then
        echo ""
        echo "[!] frontend/package.json version is ${NPM_VERSION} — expected 0.1.0 for a fresh scaffold."
        RC=1
    fi
fi

# TODO authors — should be replaced with the Kinetics default (or the
# user's own override) by init-plugin.sh.
TODO_AUTHORS=$(grep -rn --include="*.toml" --include="*.json" "TODO author name" . 2>/dev/null || true)
if [ -n "$TODO_AUTHORS" ]; then
    echo ""
    echo "[!] TODO author placeholders still present:"
    echo "$TODO_AUTHORS"
    RC=1
fi

if [ $RC -eq 0 ]; then
    echo "OK — no residuals detected."
fi

exit $RC
