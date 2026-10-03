#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/.local/share/kaliaccess"
VENV="${ROOT}/venv"
BIN="${HOME}/.local/bin"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "$ROOT" "$BIN"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$REPO_ROOT/requirements-client.txt"
cp "$SCRIPT_DIR/winctl.py" "$ROOT/winctl.py"

cat > "$BIN/winctl" <<WRAPPER
#!/usr/bin/env bash
exec "$VENV/bin/python" "$ROOT/winctl.py" "\$@"
WRAPPER
chmod +x "$BIN/winctl"

echo "Installed: $BIN/winctl"
echo "If ~/.local/bin is not in PATH, run:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
echo "Then configure Windows with:"
echo "  winctl setup <WINDOWS-IP> --username <USERNAME>"
