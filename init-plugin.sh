#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# init-plugin.sh — rename this fork from the "hello" demo plugin to your own.
#
# This repo is simultaneously:
#   1. A working demo plugin named `hello` (installable as-is for dogfood).
#   2. A scaffold you fork via `gh repo create --template` to bootstrap
#      your own plugin. In that second case, run this script once to
#      rename every occurrence of `hello` → <your-namespace>.
#
# Usage:
#   ./init-plugin.sh <namespace> "<description>" <category>
#
# Example:
#   ./init-plugin.sh pennylane "Pennylane integration — invoices & treasury" finance
#
# What it does — targeted, identifier-scoped replacements (no blind
# search/replace so the word "hello" stays intact in prose / docstrings):
#
#   piilot_pack_hello         → piilot_pack_<ns>      (Python package)
#   piilot-pack-hello         → piilot-pack-<ns>      (PyPI package name)
#   piilot-pack-hello-ui      → piilot-pack-<ns>-ui   (npm package name)
#   namespace = "hello"       → namespace = "<ns>"    (manifest)
#   "hello":                  → "<ns>":               (JSON root key in locales)
#   'hello'                   → '<ns>'                (single-quoted in TS)
#   hello = "..."             → <ns> = "..."          (entry-point key in TOML)
#   hello.<word>              → <ns>.<word>           (ids like hello.hello)
#   hello.*                   → <ns>.*                (manifest permission glob)
#   hello_<word>              → <ns>_<word>           (snake-case ids)
#   002_hello_<...>.sql       → 002_<ns>_<...>.sql    (migration filenames)
#   CREATE SCHEMA IF NOT EXISTS hello  → …<ns>
#   REFERENCES hello.         → REFERENCES <ns>.
#   ON hello.                 → ON <ns>.
#   version = "<template>"    → version = "0.1.0"     (pyproject + package.json)
#   "TODO author name <TODO@example.com>" → Kinetics default
#
# The description and category replace their current values in pyproject.toml.
# Finally the script renames the package directory and self-destructs so the
# scaffolded plugin doesn't keep it around.
# ---------------------------------------------------------------------------

set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <namespace> \"<description>\" <category>" >&2
    echo "  namespace   lower snake_case (e.g. pennylane)" >&2
    echo "  description 10-300 chars, quoted" >&2
    echo "  category    finance|hr|crm|legal|vertical|productivity|integration|other" >&2
    exit 2
fi

NAMESPACE="$1"
DESCRIPTION="$2"
CATEGORY="$3"

# --- Sanity checks ---------------------------------------------------------

if [ ! -d "piilot_pack_hello" ]; then
    echo "ERROR: piilot_pack_hello/ not found — either this script already ran," >&2
    echo "       or you're not at the repo root." >&2
    exit 1
fi

if [ "$NAMESPACE" = "hello" ]; then
    echo "ERROR: namespace 'hello' is the template's own namespace — pick a different one." >&2
    exit 1
fi

# --- Input validation ------------------------------------------------------

RESERVED=(piilot core sdk admin api public auth billing integrations \
          agents modules knowledge users companies projects)

if [[ ! "$NAMESPACE" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "ERROR: namespace must match ^[a-z][a-z0-9_]*$ (lower snake_case)" >&2
    exit 1
fi

for r in "${RESERVED[@]}"; do
    if [ "$NAMESPACE" = "$r" ]; then
        echo "ERROR: namespace '$NAMESPACE' is reserved by the Piilot core" >&2
        exit 1
    fi
done

DESC_LEN=${#DESCRIPTION}
if [ "$DESC_LEN" -lt 10 ] || [ "$DESC_LEN" -gt 300 ]; then
    echo "ERROR: description must be 10-300 chars (got $DESC_LEN)" >&2
    exit 1
fi

VALID_CATS=(finance hr crm legal vertical productivity integration other)
CAT_OK=0
for c in "${VALID_CATS[@]}"; do
    if [ "$CATEGORY" = "$c" ]; then CAT_OK=1; break; fi
done
if [ "$CAT_OK" -ne 1 ]; then
    echo "ERROR: category must be one of: ${VALID_CATS[*]}" >&2
    exit 1
fi

# --- Scaffold rewrite ------------------------------------------------------

# 1. Rename the package dir
mv piilot_pack_hello "piilot_pack_${NAMESPACE}"

# Files we scan (text files, repo root down to anywhere but .git).
# ``.ts`` / ``.tsx`` MUST be included so the frontend scaffold
# (``frontend/src/HelloModuleView.tsx``, ``frontend/src/index.ts``) is
# rewritten too. Without these, ``t('hello.module.X')`` and
# ``registerI18nBundle('hello', ...)`` slipped through and the runtime
# i18n namespace mismatched the backend's (silent UI label fallback).
FILES=$(find . -type f \
    \( -name "*.py" -o -name "*.toml" -o -name "*.md" \
       -o -name "*.json" -o -name "*.sql" -o -name "*.yml" \
       -o -name "*.yaml" -o -name "*.ts" -o -name "*.tsx" \
       -o -name "CODEOWNERS" \) \
    -not -path "./.git/*" \
    -not -path "./node_modules/*")

# Escape the description for sed (handles /, &, \)
ESCAPED_DESC=$(printf '%s\n' "$DESCRIPTION" | sed -e 's/[\/&\\]/\\&/g')
# Escape any character that sed treats specially in REPLACEMENT side
ESCAPED_NS=$(printf '%s\n' "$NAMESPACE" | sed -e 's/[\/&\\]/\\&/g')

for f in $FILES; do
    # 2a. Identifier-scoped replacements that are safe everywhere
    sed -i \
        -e "s/piilot_pack_hello/piilot_pack_${ESCAPED_NS}/g" \
        -e "s/piilot-pack-hello-ui/piilot-pack-${ESCAPED_NS}-ui/g" \
        -e "s/piilot-pack-hello/piilot-pack-${ESCAPED_NS}/g" \
        -e "s/namespace = \"hello\"/namespace = \"${ESCAPED_NS}\"/g" \
        -e "s/\"hello\":/\"${ESCAPED_NS}\":/g" \
        -e "s/hello\\.\\([a-z0-9_]\\)/${ESCAPED_NS}.\\1/g" \
        -e "s/hello_\\([a-z0-9]\\)/${ESCAPED_NS}_\\1/g" \
        -e "s|/plugins/hello/\\([a-z0-9_]\\)|/plugins/${ESCAPED_NS}/\\1|g" \
        -e "s/Plugin: hello/Plugin: ${ESCAPED_NS}/g" \
        -e "s/CREATE SCHEMA IF NOT EXISTS hello/CREATE SCHEMA IF NOT EXISTS ${ESCAPED_NS}/g" \
        -e "s/REFERENCES hello\\./REFERENCES ${ESCAPED_NS}./g" \
        -e "s/ON hello\\./ON ${ESCAPED_NS}./g" \
        "$f"

    # 2b. Bare "hello" literal in code / config — NOT in markdown prose
    #     (markdown may legitimately contain the English word "hello")
    case "$f" in
        *.py|*.toml|*.json|*.sql|*.yml|*.yaml)
            sed -i -e "s/\"hello\"/\"${ESCAPED_NS}\"/g" "$f"
            ;;
        *.ts|*.tsx)
            # TS / TSX uses single-quoted strings (e.g.
            # ``core.registerI18nBundle('hello', 'fr', ...)``). Without
            # this the i18n bundle namespace stays ``'hello'`` and the
            # backend-derived label_keys (``<ns>.modules.…``) fall back
            # to the i18n key itself in the UI.
            sed -i -e "s/'hello'/'${ESCAPED_NS}'/g" "$f"
            ;;
    esac

    # 2c. Manifest permission globs and other ``hello.*`` literals.
    # The identifier-scoped regex above (``hello\.<letter>``) doesn't
    # match the wildcard ``*`` so ``permissions.writes = ["hello.*"]``
    # slipped through. Run a targeted, narrowly-scoped replacement on
    # TOML files only (avoids over-replacing in markdown prose).
    case "$f" in
        *.toml)
            sed -i -e "s/\"hello\\.\\*\"/\"${ESCAPED_NS}.*\"/g" "$f"
            ;;
    esac

    # 2d. TOML entry-point key — left-hand side ``hello = "...":Plugin``
    # under ``[project.entry-points."piilot.plugins"]``. The previous
    # regex only rewrote the right-hand-side package name; the EP key
    # itself stayed ``hello`` and the SDK loader fell back to manifest
    # namespace lookup with a one-line warning.
    case "$f" in
        *.toml)
            sed -i -E -e "s/^hello = (\"piilot_pack_)/${ESCAPED_NS} = \\1/g" "$f"
            ;;
    esac
done

# 3a. pyproject.toml — replace the description and category values
sed -i \
    -e "s/^description = .*/description = \"${ESCAPED_DESC}\"/" \
    -e "s/^category = .*/category = \"${CATEGORY}\"/" \
    pyproject.toml

# 3b. Reset version to 0.1.0 in both pyproject.toml and frontend/package.json.
# The template itself bumps its own version as it tracks SDK releases —
# without this reset the scaffolded plugin inherits the template's version
# (e.g. 0.4.0) and PyPI / npm publishing of the user's first ``v0.1.0``
# tag fails because the metadata doesn't match the tag.
sed -i -E -e 's/^version = "[0-9]+\.[0-9]+\.[0-9]+([a-z0-9.+-]*)"$/version = "0.1.0"/' pyproject.toml
if [ -f "frontend/package.json" ]; then
    sed -i -E -e 's/"version": "[0-9]+\.[0-9]+\.[0-9]+([a-z0-9.+-]*)"/"version": "0.1.0"/' frontend/package.json
fi

# 3c. Replace the TODO author placeholder with the Kinetics default.
# Most plugins forking this template are internal; third-party authors
# can override after init by editing pyproject.toml + frontend/package.json
# (the script's "Next steps" output reminds them to do so).
DEFAULT_AUTHOR_NAME="Kinetics Consulting V2"
DEFAULT_AUTHOR_EMAIL="contact@piilot.ai"
sed -i \
    -e "s/{ name = \"TODO author name\", email = \"TODO@example.com\" }/{ name = \"${DEFAULT_AUTHOR_NAME}\", email = \"${DEFAULT_AUTHOR_EMAIL}\" }/" \
    pyproject.toml
if [ -f "frontend/package.json" ]; then
    sed -i \
        -e "s/\"author\": \"TODO author name <TODO@example.com>\"/\"author\": \"${DEFAULT_AUTHOR_NAME} <${DEFAULT_AUTHOR_EMAIL}>\"/" \
        frontend/package.json
fi

# 3d. Rename namespace-prefixed migration filenames. The migration
# DDL itself is rewritten by the schema/identifier seds above, but the
# filename ``002_hello_counter.sql`` keeps the literal ``hello`` and
# the runner doesn't care — until a second plugin with the same migration
# slug ships in the same Piilot host and they collide on disk.
MIG_DIR="piilot_pack_${NAMESPACE}/migrations"
if [ -d "$MIG_DIR" ]; then
    for old in "$MIG_DIR"/*hello*.sql; do
        [ -e "$old" ] || continue
        new="${old//hello/${NAMESPACE}}"
        if [ "$old" != "$new" ]; then
            mv "$old" "$new"
        fi
    done
fi

# 3e. CLAUDE.md / README.md — replace the banner description one more time
sed -i "s/Hello world plugin — Piilot SDK scaffold starter\\./${ESCAPED_DESC}/g" README.md CLAUDE.md CHANGELOG.md 2>/dev/null || true

# --- Post-init residual check ----------------------------------------------
# Run an opt-in audit (./scripts/post-init-check.sh) the user can re-run
# any time. Skip the call here if the file isn't present (older forks).

if [ -x "scripts/post-init-check.sh" ]; then
    echo ""
    echo "--- Running post-init residual check ---"
    ./scripts/post-init-check.sh "${NAMESPACE}" || true
fi

# --- Done ------------------------------------------------------------------

cat <<EOF

Plugin scaffolded as piilot-pack-${NAMESPACE}.

Next steps:

  1. Review pyproject.toml:
     - authors[0].name / email (default: Kinetics Consulting V2 — override if
       you fork as a third party)
     - urls.homepage (points to the Kinetics-Consulting-V2 fork name by default)
     - supported_modes if you don't support both saas + selfhosted
     - Uncomment icon = "./assets/icon.svg" when you ship an icon

  2. (Optional) Rename the default module id ``${NAMESPACE}.dashboard``
     in pyproject.toml + seeds.py if your plugin's primary surface is
     not a dashboard (e.g. ``${NAMESPACE}.import``,
     ``${NAMESPACE}.settings``). Both files reference the same id —
     change them together. The default ``dashboard`` is fine for
     single-module hello-world / starter plugins.

  3. Skim README.md for any remaining "hello" in prose (we only replaced
     identifiers, not English prose) and rewrite the intro if needed.

  4. Commit the scaffold:
       git add .
       git commit -m "Initial scaffold for piilot-pack-${NAMESPACE}"

  5. Install locally:
       pip install -e .[dev]

  6. Run the smoke tests:
       pytest

  7. Bind-mount into AICockpit/docker-compose.override.yml (gitignored)
     to test inside a real Piilot backend, then restart the backend and
     watch for [plugins] Loaded: ${NAMESPACE} v0.1.0 in the logs.

Happy plugin writing.
EOF

# Self-remove so the scaffolded plugin doesn't keep this script around
rm -- "$0"
