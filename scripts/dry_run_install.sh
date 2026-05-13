#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/dry_run_install.sh — automate the §1 dry-run of
# docs/sdk/PLUGIN_DEV_WORKFLOW.md before tagging a stable v0.1.0.
#
# What it does:
#
#   1. Bumps the package version to <version>rc1 (pyproject.toml).
#   2. Builds a wheel + sdist locally.
#   3. (optional) Uploads the rc to TestPyPI.
#   4. (optional) Boots a Piilot core docker compose, installs the rc
#      from TestPyPI, and greps the backend logs for SKIP / FAIL-SOFT.
#   5. Reports a verdict (clean / dirty) so you know if v0.1.0 stable
#      is safe to tag.
#
# Usage:
#
#     ./scripts/dry_run_install.sh <version> [--upload] [--core <path>]
#
#     <version>    Target stable version (e.g. 0.1.0). The rc tag is
#                  derived as <version>rc1.
#     --upload     Upload the built artifacts to TestPyPI (requires
#                  TWINE_USERNAME=__token__ + TWINE_PASSWORD or
#                  ~/.pypirc with a `testpypi` section).
#     --core PATH  Path to a local AICockpit checkout with compose.dev.yml.
#                  When provided, the script boots the core, installs
#                  the rc from TestPyPI, tails the backend logs for 60s
#                  and greps for SKIP / FAIL-SOFT lines.
#
# Exit codes:
#   0 — dry run clean (no SKIP / FAIL-SOFT in logs, plugins_registry row OK)
#   1 — residuals found (logs show SKIP / FAIL-SOFT for this plugin)
#   2 — usage / build error
#   3 — upload error (TestPyPI rejected)
#
# Requirements:
#   build · twine (only when --upload) · docker · jq · grep
#
# Caveat:
#   `python -m build` runs in the current venv. Activate the plugin's
#   dev venv first (`pip install -e .[dev]`) so the build pulls the
#   right deps.
# ---------------------------------------------------------------------------

set -uo pipefail

usage() {
    cat <<USAGE >&2
Usage: $0 <version> [--upload] [--core <path>]

  <version>     Target stable version (e.g. 0.1.0). rc tag = <version>rc1.
  --upload      Upload the rc to TestPyPI.
  --core PATH   Path to AICockpit checkout — will boot core + grep logs.

Examples:
  $0 0.1.0                               # build only, no upload
  $0 0.1.0 --upload                      # build + push to TestPyPI
  $0 0.1.0 --upload --core ../AICockpit  # full E2E
USAGE
    exit 2
}

if [ "$#" -lt 1 ]; then usage; fi

VERSION="$1"
shift
UPLOAD=0
CORE_PATH=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --upload) UPLOAD=1 ;;
        --core)
            shift
            CORE_PATH="${1:-}"
            if [ -z "$CORE_PATH" ]; then usage; fi
            ;;
        *) usage ;;
    esac
    shift
done

RC_VERSION="${VERSION}rc1"
PLUGIN_NS=$(awk -F'"' '/^namespace = "/ {print $2; exit}' pyproject.toml)
PLUGIN_PYPI_NAME=$(awk -F'"' '/^name = "/ {print $2; exit}' pyproject.toml)

if [ -z "$PLUGIN_NS" ] || [ -z "$PLUGIN_PYPI_NAME" ]; then
    echo "ERROR: Could not infer namespace or PyPI name from pyproject.toml" >&2
    exit 2
fi

echo "==> Plugin: $PLUGIN_PYPI_NAME (namespace=$PLUGIN_NS)"
echo "==> Stable target: $VERSION"
echo "==> RC tag: $RC_VERSION"

# 1. Bump version to rc in a worktree tmp file (we won't commit this)
echo ""
echo "==> Step 1: bumping pyproject version → $RC_VERSION"
cp pyproject.toml pyproject.toml.bak
trap 'mv pyproject.toml.bak pyproject.toml 2>/dev/null || true' EXIT
sed -i.tmp -E "s/^(version = )\"[^\"]+\"/\1\"$RC_VERSION\"/" pyproject.toml
rm -f pyproject.toml.tmp

# 2. Build wheel + sdist
echo ""
echo "==> Step 2: building wheel + sdist"
rm -rf dist/
python -m build --wheel --sdist --outdir dist/ 2>&1 | tail -5
WHEEL=$(ls dist/*.whl 2>/dev/null | head -1)
SDIST=$(ls dist/*.tar.gz 2>/dev/null | head -1)

if [ -z "$WHEEL" ] || [ -z "$SDIST" ]; then
    echo "ERROR: build did not produce dist/*.whl + dist/*.tar.gz" >&2
    exit 2
fi
echo "    Built: $WHEEL"
echo "    Built: $SDIST"

# 3. Upload to TestPyPI if requested
if [ "$UPLOAD" -eq 1 ]; then
    echo ""
    echo "==> Step 3: uploading to TestPyPI"
    if ! command -v twine >/dev/null 2>&1; then
        echo "ERROR: twine not on PATH. Install with: pip install twine" >&2
        exit 3
    fi
    twine upload --repository testpypi dist/* 2>&1 | tail -10
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        echo "ERROR: TestPyPI upload failed" >&2
        exit 3
    fi
    echo "    Uploaded: https://test.pypi.org/project/${PLUGIN_PYPI_NAME}/${RC_VERSION}/"
fi

# 4. Boot core + grep logs (only if --core given AND --upload happened)
if [ -n "$CORE_PATH" ]; then
    if [ "$UPLOAD" -eq 0 ]; then
        echo ""
        echo "WARN: --core needs --upload (the core fetches the rc from TestPyPI)" >&2
        echo "      Re-run with --upload --core $CORE_PATH" >&2
        exit 2
    fi

    echo ""
    echo "==> Step 4: booting AICockpit core at $CORE_PATH and watching for SKIP/FAIL-SOFT"
    if [ ! -f "$CORE_PATH/compose.dev.yml" ]; then
        echo "ERROR: $CORE_PATH/compose.dev.yml not found" >&2
        exit 2
    fi

    # Pin the plugin to the rc version on TestPyPI in a temporary
    # requirements override.
    PIN_LINE="${PLUGIN_PYPI_NAME} @ https://test.pypi.org/simple/${PLUGIN_PYPI_NAME}/${RC_VERSION}"
    echo "    Pinning core to: $PIN_LINE"

    pushd "$CORE_PATH" >/dev/null
    cp backend/api/requirements.txt backend/api/requirements.txt.bak

    # Replace any existing pin for this plugin, otherwise append.
    if grep -q "^${PLUGIN_PYPI_NAME}" backend/api/requirements.txt; then
        sed -i.tmp "s|^${PLUGIN_PYPI_NAME}.*|${PIN_LINE}|" backend/api/requirements.txt
    else
        echo "$PIN_LINE" >> backend/api/requirements.txt
    fi
    rm -f backend/api/requirements.txt.tmp

    # Add TestPyPI to pip extra-index-url at install time.
    docker compose -f compose.dev.yml build --no-cache --build-arg PIP_EXTRA_INDEX_URL=https://test.pypi.org/simple/ backend 2>&1 | tail -5

    # Boot for 60s, capture logs, kill.
    docker compose -f compose.dev.yml up -d backend
    sleep 60
    LOGS=$(docker compose -f compose.dev.yml logs backend 2>&1)
    docker compose -f compose.dev.yml down

    # Restore requirements.
    mv backend/api/requirements.txt.bak backend/api/requirements.txt
    popd >/dev/null

    # Grep for SKIP / FAIL-SOFT on this plugin's namespace.
    echo ""
    echo "==> Step 5: scanning logs for SKIP / FAIL-SOFT"
    SKIPS=$(echo "$LOGS" | grep -E "\[plugins\] (SKIP|FAIL-SOFT) .*${PLUGIN_NS}" || true)
    LOADED=$(echo "$LOGS" | grep -E "\[plugins\] Loaded: ${PLUGIN_NS}" || true)

    if [ -n "$SKIPS" ]; then
        echo "    ❌ FOUND ISSUES:"
        echo "$SKIPS" | sed 's/^/        /'
        exit 1
    fi
    if [ -z "$LOADED" ]; then
        echo "    ❌ Plugin never logged 'Loaded'. Did discovery find it?"
        echo "$LOGS" | grep "\[plugins\]" | head -10 | sed 's/^/        /'
        exit 1
    fi
    echo "    ✅ Loaded cleanly:"
    echo "$LOADED" | sed 's/^/        /'
fi

echo ""
echo "==> Dry run clean. Safe to tag stable v$VERSION."
echo "    git tag v$VERSION && git push origin v$VERSION"
