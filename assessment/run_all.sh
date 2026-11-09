#!/usr/bin/env bash
# Install, run each solution's own test suite, then drive its server with probe.py
# (fresh start, then a restart on the same data to check persistence).
# Output: assessment/results/<solution>.{setup,tests,probe}.txt
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/assessment/results"
mkdir -p "$OUT"
TOKEN="$(openssl rand -hex 32)" # throwaway, generated per run
PORT=18080

setup() {
  case "$1" in
    claude-fable) uv sync ;;
    claude-opus|claude-sonnet) go build -o ./.probe-bin ./cmd/snip ;;
    claude-haiku) true ;;
    codex-gpt-5.6-terra) npm install --no-audit --no-fund ;;
    codex-gpt-6.1-sol) python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt ;;
    *) true ;;
  esac
}

tests() {
  case "$1" in
    claude-fable) uv run pytest -q ;;
    claude-opus|claude-sonnet) go vet ./... && go test -race -count=1 ./... ;;
    claude-haiku|codex-gpt-5.6-terra) npm test ;;
    codex-gpt-6.1-sol) .venv/bin/python -m unittest discover -v ;;
    codex-gpt-6.1-terra) python3 -m unittest -v ;;
    *) python3 -m unittest discover -s tests -v ;;
  esac
}

start() { # $1 solution, $2 data dir
  local d="$2" base="http://127.0.0.1:$PORT"
  export SNIP_API_TOKEN="$TOKEN" SNIP_BASE_URL="$base" SNIP_PUBLIC_BASE_URL="$base"
  export PORT SNIP_HOST=127.0.0.1 SNIP_PORT=$PORT SNIP_ADDR="127.0.0.1:$PORT"
  export SNIP_DB_PATH="$d/snip.db" SNIP_DB="$d/snip.db" SNIP_DATA_FILE="$d/links.json"
  case "$1" in
    claude-fable) uv run python -m snip ;;
    claude-opus|claude-sonnet) ./.probe-bin ;;
    claude-haiku|codex-gpt-5.6-terra) npm start ;;
    codex-gpt-5.6-luna) python3 -m snip --host 127.0.0.1 --port $PORT --db "$d/snip.db" --base-url "$base" ;;
    codex-gpt-6.1-sol) .venv/bin/python -m snip ;;
    codex-gpt-6.1-terra) python3 snip.py ;;
    *) python3 -m snip ;;
  esac
}

wait_up() {
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

stop() {
  pkill -TERM -P "$1" 2>/dev/null; kill -TERM "$1" 2>/dev/null; wait "$1" 2>/dev/null; sleep 0.5
  lsof -ti tcp:$PORT -sTCP:LISTEN | xargs kill -TERM 2>/dev/null; sleep 0.5
}

for dir in "$ROOT"/solutions/*/; do
  s="$(basename "$dir")"
  [ $# -gt 0 ] && [[ " $* " != *" $s "* ]] && continue
  echo "== $s"
  cd "$dir" || continue
  setup "$s" >"$OUT/$s.setup.txt" 2>&1
  tests "$s" >"$OUT/$s.tests.txt" 2>&1; echo "exit=$?" >>"$OUT/$s.tests.txt"

  data="$(mktemp -d)"; state="$data/state.json"; : >"$OUT/$s.probe.txt"
  (start "$s" "$data" >"$OUT/$s.server1.log" 2>&1) & pid=$!
  if wait_up; then
    python3 -I "$ROOT/assessment/probe.py" "http://127.0.0.1:$PORT" "$TOKEN" phase1 "$state" >>"$OUT/$s.probe.txt" 2>&1
  else
    echo '{"id": "server_start", "ok": false, "detail": "did not come up"}' >>"$OUT/$s.probe.txt"
  fi
  stop $pid
  (start "$s" "$data" >"$OUT/$s.server2.log" 2>&1) & pid=$!
  if wait_up && [ -f "$state" ]; then
    python3 -I "$ROOT/assessment/probe.py" "http://127.0.0.1:$PORT" "$TOKEN" phase2 "$state" >>"$OUT/$s.probe.txt" 2>&1
  fi
  stop $pid
  rm -rf "$data" ./.probe-bin
  echo "   probe: $(grep -c '"ok": true' "$OUT/$s.probe.txt") pass / $(grep -c '"ok": false' "$OUT/$s.probe.txt") fail; tests: $(tail -1 "$OUT/$s.tests.txt")"
done
