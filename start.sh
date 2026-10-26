#!/usr/bin/env bash
# ATI Terminal – one-click start for macOS/Linux (macOS: double-click Start.command).
# Installs "uv" (incl. Python) if needed, sets everything up, starts server + dashboard and
# opens the browser. Keep the window open while you use it.
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  ==========================================="
echo "   ATI Terminal – Market Intelligence"
echo "   Analyse only – es werden keine Orders ausgeführt"
echo "  ==========================================="
echo

# 1) uv
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "[1/4] uv wird installiert (einmalig) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { echo "FEHLER: uv nicht verfügbar – https://docs.astral.sh/uv/"; exit 1; }
echo "[1/4] uv gefunden."

# 2) Alpaca keys (first start only)
if [ ! -f config/alpaca.env ]; then
  echo
  echo "[2/4] Alpaca-Keys einrichten (einmalig). Leer lassen = DEMO-Modus mit simulierten Daten."
  read -r -p "      API Key ID:     " AKEY || AKEY=""
  read -r -p "      API Secret Key: " ASEC || ASEC=""
  mkdir -p config
  umask 077
  printf '# Alpaca Market Data Keys (nur lokal, nicht auf GitHub)\nALPACA_API_KEY_ID=%s\nALPACA_API_SECRET_KEY=%s\n' \
    "$AKEY" "$ASEC" > config/alpaca.env
  echo "      Gespeichert in config/alpaca.env"
else
  echo "[2/4] Alpaca-Keys vorhanden (config/alpaca.env)."
fi

# 3) dependencies
echo "[3/4] Abhängigkeiten werden geprüft (erster Start: einige Minuten) ..."
uv sync --project backend --frozen --no-dev

# 4) start
mkdir -p data
export DATABASE_URL="sqlite+aiosqlite:///./data/ati.db"
URL="http://127.0.0.1:8000"
echo "[4/4] Server startet – der Browser öffnet sich automatisch: $URL"
echo "      Zum Beenden dieses Fenster schließen oder Strg+C drücken."
echo
(
  for _ in $(seq 1 180); do
    if curl -sf "$URL/api/health" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1; fi
      break
    fi
    sleep 1
  done
) &
exec uv run --project backend --frozen --no-dev uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
