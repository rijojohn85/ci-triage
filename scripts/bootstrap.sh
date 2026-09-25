#!/usr/bin/env bash
# Bootstrap: creates .venv, installs pinned Python deps, npm installs pinned promptfoo/smee-client,
# verifies each pin, prints versions: block. On any pin mismatch: report and exit 2, never substitute.
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
PYTHON_MIN=3.10
PIN_MISMATCH=0

# Single-source pin lists (pyproject.toml carries the same Python pins for install).
PY_PINS=(
  "a2a-sdk 1.1.5"
  "typesafe-sdk 0.7.1"
  "anthropic 1.8.0"
  "pydantic 2.13.5"
  "psycopg 3.3.6"
)
NPM_PINS=(
  "promptfoo 0.123.1"
  "smee-client 5.0.0"
)

report_mismatch() {
  echo "PIN MISMATCH: $1 expected $2: $3"
  PIN_MISMATCH=1
}

fail_and_exit_2() {
  echo "Bootstrap failed. No substitutes installed."
  exit 2
}

# --print-versions: validate + print only; skip installs when env already present.
PRINT_ONLY=0
if [ "${1:-}" = "--print-versions" ]; then
  PRINT_ONLY=1
fi

# ---- Preflight (before any install) ----
if ! pyver="$("$PY" -c 'import platform; print(platform.python_version())' 2>/dev/null)"; then
  report_mismatch "python >= ${PYTHON_MIN}" "${PYTHON_MIN}" "interpreter '$PY' not runnable"
  fail_and_exit_2
fi
pyok="$("$PY" -c "
import sys
minv = tuple(int(x) for x in '${PYTHON_MIN}'.split('.'))
cur = sys.version_info[: len(minv)]
print('ok' if cur >= minv else 'bad')
")"
if [ "$pyok" != "ok" ]; then
  report_mismatch "python >= ${PYTHON_MIN}" "${PYTHON_MIN}" "found Python ${pyver}; need >= ${PYTHON_MIN}"
  fail_and_exit_2
fi
for cmd in node npm; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    report_mismatch "node/npm toolchain" "node + npm on PATH" "command '$cmd' not found"
    fail_and_exit_2
  fi
done
echo "preflight: python ${pyver}, node $(node --version), npm $(npm --version)"

# ---- Env creation / installs ----
if [ "$PRINT_ONLY" -eq 1 ] && [ -d .venv ] && [ -d node_modules ]; then
  echo "--print-versions: env present, skipping installs"
else
  if [ ! -d .venv ]; then
    echo "== creating .venv =="
    "$PY" -m venv .venv
  fi
  # shellcheck source=/dev/null
  source .venv/bin/activate

  echo "== installing pinned Python deps =="
  if [ -f requirements/constraints.txt ]; then
    if ! pip_err="$(pip install -e . -c requirements/constraints.txt 2>&1)"; then
      report_mismatch "python install of project pins" "all pins installable under constraints" "pip install 'triage' failed: $(echo "$pip_err" | tail -n 3 | tr '\n' ' ')"
      fail_and_exit_2
    fi
  else
    if ! pip_err="$(pip install -e . 2>&1)"; then
      report_mismatch "python install of project pins" "all pins installable" "pip install 'triage' failed: $(echo "$pip_err" | tail -n 3 | tr '\n' ' ')"
      fail_and_exit_2
    fi
    mkdir -p requirements
    pip freeze | grep -v -e '^-e ' -e '^## !!' > requirements/constraints.txt
    echo "NOTE: constraints file was absent; installed directly and generated requirements/constraints.txt from the installed .venv."
  fi

  echo "== npm install =="
  if [ -f package-lock.json ]; then
    if ! npm_err="$(npm ci 2>&1)"; then
      echo "$npm_err"
      report_mismatch "npm install of project pins" "npm ci clean" "npm ci failed: see npm output above"
      fail_and_exit_2
    fi
  else
    if ! npm_err="$(npm install 2>&1)"; then
      echo "$npm_err"
      report_mismatch "npm install of project pins" "npm install successful" "npm install failed: see npm output above"
      fail_and_exit_2
    fi
    echo "NOTE: no package-lock.json committed; ran npm install. Commit package-lock.json for reproducibility."
  fi
fi
[ -f .venv/bin/activate ] && source .venv/bin/activate

verify_py() { # meta pin
  local meta="$1" pin="$2" actual=""
  if ! actual="$("$PYTHON" -c "import importlib.metadata as m; print(m.version('$meta'))" 2>/dev/null)"; then
    report_mismatch "$meta" "$pin" "package '$meta' not importable in .venv"
    return
  fi
  if [ "$actual" != "$pin" ]; then
    report_mismatch "$meta" "$pin" "installed version is $actual"
  fi
}

verify_npm() { # name pin
  local name="$1" pin="$2" actual="" ls_line=""
  # ground truth: the really installed artifact in node_modules
  if ! actual="$(node -e "const fs=require('fs');console.log(JSON.parse(fs.readFileSync('node_modules/'+'$name'+'/package.json')).version)" 2>/dev/null)"; then
    actual=""
  fi
  ls_line="$(npm ls "$name" --depth=0 2>/dev/null | grep -oE "$name@[^[:space:]]+" | head -1 || true)"
  if [ -z "$actual" ]; then
    report_mismatch "$name@$pin" "$pin" "package '$name' not found in node_modules (npm ls: ${ls_line:-nothing})"
  elif [ "$actual" != "$pin" ]; then
    report_mismatch "$name@$pin" "$pin" "installed version is $actual (npm ls: ${ls_line:-nothing})"
  fi
}

print_versions() {
  echo "versions:"
  echo "  python: $("$PYTHON" -c 'import platform; print(platform.python_version())')"
  echo "  node: $(node --version)"
  echo "  npm: $(npm --version)"
  for entry in "${PY_PINS[@]}"; do
    echo "  ${entry%% *}: $("$PYTHON" -c "import importlib.metadata as m; print(m.version('${entry%% *}'))" 2>/dev/null || echo MISSING)"
  done
  for entry in "${NPM_PINS[@]}"; do
    echo "  ${entry%% *} (npm): $(node -e "const fs=require('fs');console.log(JSON.parse(fs.readFileSync('node_modules/${entry%% *}/package.json')).version)" 2>/dev/null || echo MISSING)"
  done
  echo "  postgresql: postgres:18 image (pinned; used from Story 0.3 compose, not installed here)"
}

# ---- Verify pins (data-driven) ----
echo "== verifying pins =="
export PYTHON=".venv/bin/python"
for entry in "${PY_PINS[@]}"; do
  verify_py "${entry%% *}" "${entry##* }"
done
for entry in "${NPM_PINS[@]}"; do
  verify_npm "${entry%% *}" "${entry##* }"
done

if [ "$PRINT_ONLY" -eq 1 ]; then
  print_versions
fi

if [ "$PIN_MISMATCH" -ne 0 ]; then
  echo "Bootstrap completed with pin mismatches (see above). No substitutes installed."
  exit 2
fi

echo "Bootstrap OK: all pins verified."
if [ "$PRINT_ONLY" -ne 1 ]; then
  print_versions
fi
