from __future__ import annotations

import argparse
import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import mss
import mss.tools
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import Response

VERSION = "1.1.0"
_events: deque[dict] = deque(maxlen=500)
_events_lock = threading.Lock()
_token = ""
_root = None
_status_var = None

app = FastAPI(title="KaliAccess Desktop Helper", version=VERSION, docs_url=None, redoc_url=None)


def require_token(value: str | None) -> None:
    if not value or value != _token:
        raise HTTPException(401, "Invalid desktop helper token")


@app.get("/status")
def status(x_kaliaccess_helper_token: str | None = Header(default=None)) -> dict:
    require_token(x_kaliaccess_helper_token)
    return {
        "ok": True,
        "version": VERSION,
        "user": os.environ.get("USERNAME", "unknown"),
        "session": os.environ.get("SESSIONNAME", "unknown"),
        "keytest_events": len(_events),
    }


@app.get("/screenshot")
def screenshot(x_kaliaccess_helper_token: str | None = Header(default=None)) -> Response:
    require_token(x_kaliaccess_helper_token)
    try:
        with mss.mss() as capture:
            monitor = capture.monitors[0]
            shot = capture.grab(monitor)
            png = mss.tools.to_png(shot.rgb, shot.size)
    except Exception as exc:
        raise HTTPException(503, f"Desktop capture unavailable: {exc}")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/keyevents")
def keyevents(
    limit: int = Query(default=100, ge=1, le=500),
    x_kaliaccess_helper_token: str | None = Header(default=None),
) -> dict:
    require_token(x_kaliaccess_helper_token)
    with _events_lock:
        rows = list(_events)[-limit:]
    return {"events": rows, "notice": "Only keys typed in the visible KaliAccess key-event test window are recorded."}


def clear_events() -> None:
    with _events_lock:
        _events.clear()
    if _status_var is not None:
        _status_var.set("Key-event test buffer cleared.")


def open_key_test() -> None:
    import tkinter as tk
    from tkinter import ttk

    if _root is None:
        return
    win = tk.Toplevel(_root)
    win.title("KaliAccess - Key-event test")
    win.geometry("720x420")

    ttk.Label(
        win,
        text="SAFE TEST MODE",
        font=("Segoe UI", 14, "bold"),
    ).pack(pady=(18, 4))
    ttk.Label(
        win,
        text="Only keys typed inside the box below are recorded. KaliAccess does not install a global keyboard hook.",
        wraplength=660,
        justify="center",
    ).pack(padx=20, pady=(0, 12))

    box = tk.Text(win, height=12, width=80, wrap="word")
    box.pack(fill="both", expand=True, padx=18, pady=8)

    local_status = tk.StringVar(value="Click inside the box and type to generate test events.")
    ttk.Label(win, textvariable=local_status).pack(pady=(0, 8))

    def on_key(event) -> None:
        char = event.char if event.char and event.char.isprintable() else ""
        row = {
            "time": datetime.now(timezone.utc).isoformat(),
            "keysym": event.keysym,
            "char": char,
        }
        with _events_lock:
            _events.append(row)
            count = len(_events)
        local_status.set(f"Captured {count} test event(s).")
        if _status_var is not None:
            _status_var.set(f"Key-event test contains {count} event(s).")

    box.bind("<KeyPress>", on_key, add="+")
    box.focus_set()
    ttk.Button(win, text="Clear test events", command=clear_events).pack(pady=(0, 14))


def run_api(port: int) -> None:
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


def main() -> None:
    global _token, _root, _status_var

    parser = argparse.ArgumentParser(description="KaliAccess interactive desktop helper")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    token_path = Path(args.token_file)
    _token = token_path.read_text(encoding="utf-8").strip()
    if len(_token) < 32:
        raise SystemExit("Desktop helper token is missing or invalid")

    import tkinter as tk
    from tkinter import ttk

    _root = tk.Tk()
    _root.title("KaliAccess Desktop Helper")
    _root.geometry("560x260")
    _root.resizable(False, False)

    ttk.Label(_root, text="KaliAccess Desktop Helper", font=("Segoe UI", 16, "bold")).pack(pady=(22, 6))
    ttk.Label(
        _root,
        text="This visible helper enables authenticated screenshots from Kali and the local key-event test window.",
        wraplength=500,
        justify="center",
    ).pack(padx=24, pady=6)

    _status_var = tk.StringVar(value=f"Running for {os.environ.get('USERNAME', 'current user')} on localhost:{args.port}")
    ttk.Label(_root, textvariable=_status_var).pack(pady=8)
    ttk.Button(_root, text="Open key-event test", command=open_key_test).pack(pady=6)
    ttk.Button(_root, text="Minimize", command=_root.iconify).pack(pady=4)

    thread = threading.Thread(target=run_api, args=(args.port,), daemon=True, name="KaliAccessDesktopAPI")
    thread.start()

    _root.after(500, _root.iconify)
    _root.mainloop()


if __name__ == "__main__":
    main()
