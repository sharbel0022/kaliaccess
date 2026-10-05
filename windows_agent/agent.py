from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import platform
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import psutil
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import UploadFile
from pydantic import BaseModel, Field

VERSION = "1.1.0"
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
INSTALL_ROOT = PROGRAM_DATA / "KaliAccess"
CONFIG_FILE = INSTALL_ROOT / "config.json"
DEFAULT_WORKSPACE = Path(r"C:\KaliAccess")
CHUNK = 1024 * 1024
security = HTTPBasic(auto_error=False)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise RuntimeError(f"KaliAccess is not configured: {CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def workspace() -> Path:
    return Path(load_config().get("workspace", str(DEFAULT_WORKSPACE)))


def resolve_path(value: str | None) -> Path:
    if not value:
        return workspace()
    path = Path(value)
    return path if path.is_absolute() else workspace() / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    cfg = load_config()
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username, cfg["username"])
    try:
        pass_ok = bcrypt.checkpw(credentials.password.encode(), cfg["password_hash"].encode("ascii"))
    except ValueError:
        pass_ok = False
    if not (user_ok and pass_ok):
        time.sleep(0.25)
        raise HTTPException(401, "Invalid KaliAccess username or password", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def clip(text: str, limit: int) -> tuple[str, bool]:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", errors="replace") + "\n[output truncated]", True


def build_shell_command(shell: str, command: str, cwd: str) -> list[str]:
    marker = "__KALIACCESS_CWD__"
    if shell == "powershell":
        safe_cwd = cwd.replace("'", "''")
        wrapped = (
            f"Set-Location -LiteralPath '{safe_cwd}'; "
            f"& {{ {command} }}; $ec=$LASTEXITCODE; if ($null -eq $ec) {{$ec=0}}; "
            f"Write-Output '{marker}'; Write-Output (Get-Location).Path; exit $ec"
        )
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped]
    if shell == "cmd":
        wrapped = (
            f'cd /d "{cwd}" && ({command}) & '
            f'set "KALIACCESS_EC=!ERRORLEVEL!" & echo {marker} & cd & exit /b !KALIACCESS_EC!'
        )
        return ["cmd.exe", "/d", "/v:on", "/s", "/c", wrapped]
    if shell == "wsl":
        cd_expr = "~" if cwd == "~" else shlex.quote(cwd)
        wrapped = f"cd {cd_expr} 2>/dev/null || cd ~; {command}; ec=$?; printf '\\n{marker}\\n'; pwd; exit $ec"
        return ["wsl.exe", "bash", "-lc", wrapped]
    raise ValueError(f"Unsupported shell: {shell}")


def run_command(shell: str, command: str, cwd: str | None, timeout: int) -> dict:
    cfg = load_config()
    shell = shell.lower()
    cwd = cwd or ("~" if shell == "wsl" else str(workspace()))
    timeout = min(max(timeout, 1), int(cfg.get("max_command_seconds", 300)))
    if shell != "wsl":
        Path(cwd).mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        result = subprocess.run(
            build_shell_command(shell, command, cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=os.environ.copy(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nCommand timed out after {timeout}s"
        code = 124
    except FileNotFoundError as exc:
        stdout, stderr, code = "", str(exc), 127
    duration = int((time.perf_counter() - started) * 1000)

    marker = "__KALIACCESS_CWD__"
    new_cwd = cwd
    if marker in stdout:
        before, after = stdout.rsplit(marker, 1)
        stdout = before.rstrip("\r\n")
        lines = after.strip().splitlines()
        if lines:
            new_cwd = lines[-1].strip()

    limit = int(cfg.get("max_output_bytes", 2 * 1024 * 1024))
    stdout, a = clip(stdout, limit)
    stderr, b = clip(stderr, limit)
    return {"stdout": stdout, "stderr": stderr, "exit_code": code, "duration_ms": duration, "cwd": new_cwd, "truncated": a or b}


def start_process(command: str, cwd: str | None) -> int:
    cwd = cwd or str(workspace())
    Path(cwd).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
    return proc.pid


class RunRequest(BaseModel):
    command: str = Field(min_length=1, max_length=100_000)
    shell: str = Field(default="powershell", pattern="^(powershell|cmd|wsl)$")
    cwd: str | None = None
    timeout: int = Field(default=60, ge=1, le=300)


class MkdirRequest(BaseModel):
    path: str


class StartRequest(BaseModel):
    command: str = Field(min_length=1, max_length=100_000)
    cwd: str | None = None


_audit_lock = threading.Lock()


def append_audit(method: str, path: str, status: int, client: str, duration_ms: int) -> None:
    try:
        target = workspace() / "logs" / "audit.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status": status,
            "client": client,
            "duration_ms": duration_ms,
        }
        with _audit_lock:
            if target.exists() and target.stat().st_size > 5 * 1024 * 1024:
                rotated = target.with_suffix(".jsonl.1")
                rotated.unlink(missing_ok=True)
                target.replace(rotated)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # Audit logging must never break remote administration.
        pass


def recent_audit(limit: int) -> list[dict]:
    target = workspace() / "logs" / "audit.jsonl"
    if not target.exists():
        return []
    with _audit_lock:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def helper_request(path: str, timeout: float = 5.0) -> tuple[bytes, str]:
    cfg = load_config()
    token = cfg.get("desktop_helper_token")
    if not token:
        raise HTTPException(503, "Desktop helper is not configured. Re-run windows_agent/install.ps1.")
    port = int(cfg.get("desktop_helper_port", 8766))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-KaliAccess-Helper-Token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(503, f"Desktop helper error: {detail or exc.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            503,
            "Desktop helper is offline. Sign in to Windows and ensure 'KaliAccess Desktop Helper' is running.",
        ) from exc


def helper_json(path: str, timeout: float = 5.0) -> dict:
    body, _ = helper_request(path, timeout=timeout)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "Desktop helper returned invalid JSON") from exc


app = FastAPI(title="KaliAccess Agent", version=VERSION, docs_url=None, redoc_url=None)


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        path = request.url.path
        if request.method != "GET" or path == "/api/files/download":
            duration_ms = int((time.perf_counter() - started) * 1000)
            client = request.client.host if request.client else "unknown"
            append_audit(request.method, path, status_code, client, duration_ms)


@app.get("/api/info")
def info(_: str = Depends(require_auth)) -> dict:
    cfg = load_config()
    return {"name": "KaliAccess Agent", "version": VERSION, "hostname": socket.gethostname(), "port": cfg["port"], "tls": True}


@app.get("/api/ping")
def ping(_: str = Depends(require_auth)) -> dict:
    return {"ok": True, "version": VERSION, "hostname": socket.gethostname()}


@app.get("/api/status")
def status(_: str = Depends(require_auth)) -> dict:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    return {
        "hostname": socket.gethostname(),
        "user": os.environ.get("USERNAME", "unknown"),
        "windows": platform.platform(),
        "cpu_percent": psutil.cpu_percent(interval=0.15),
        "ram_used": vm.used,
        "ram_total": vm.total,
        "disk_used": disk.used,
        "disk_total": disk.total,
        "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
        "workspace": str(workspace()),
        "wsl_available": shutil.which("wsl.exe") is not None,
        "python_available": shutil.which("python.exe") is not None or shutil.which("python") is not None,
        "agent_version": VERSION,
    }


@app.get("/api/desktop/status")
def api_desktop_status(_: str = Depends(require_auth)) -> dict:
    return helper_json("/status")


@app.get("/api/desktop/screenshot")
def api_desktop_screenshot(_: str = Depends(require_auth)) -> Response:
    body, _ = helper_request("/screenshot", timeout=10.0)
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/keytest/events")
def api_keytest_events(
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(require_auth),
) -> dict:
    return helper_json(f"/keyevents?limit={limit}")


@app.get("/api/logs/audit")
def api_audit_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_auth),
) -> dict:
    return {"events": recent_audit(limit)}


@app.post("/api/run")
def api_run(payload: RunRequest, _: str = Depends(require_auth)) -> dict:
    return run_command(payload.shell, payload.command, payload.cwd, payload.timeout)


@app.get("/api/files/list")
def api_list(path: str | None = Query(default=None), _: str = Depends(require_auth)) -> dict:
    target = resolve_path(path)
    if not target.exists():
        raise HTTPException(404, f"Path not found: {target}")
    if not target.is_dir():
        raise HTTPException(400, f"Not a directory: {target}")
    rows = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            st = child.stat()
            size, modified = st.st_size, st.st_mtime
        except OSError:
            size, modified = None, None
        rows.append({"name": child.name, "path": str(child), "is_dir": child.is_dir(), "size": size, "modified": modified})
    return {"path": str(target), "entries": rows}


@app.post("/api/files/mkdir")
def api_mkdir(payload: MkdirRequest, _: str = Depends(require_auth)) -> dict:
    target = resolve_path(payload.path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(target)}


@app.post("/api/files/upload")
async def api_upload(file: UploadFile = File(...), destination: str | None = Form(default=None), _: str = Depends(require_auth)) -> dict:
    if not destination:
        dest = resolve_path("uploads")
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / (file.filename or "upload.bin")
    else:
        dest = resolve_path(destination)
        if destination.endswith("/") or destination.endswith("\\") or dest.is_dir():
            dest = dest / (file.filename or "upload.bin")
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open("wb") as handle:
        while True:
            block = await file.read(CHUNK)
            if not block:
                break
            handle.write(block)
            written += len(block)
    return {"ok": True, "path": str(dest), "bytes": written, "sha256": sha256_file(dest)}


@app.get("/api/files/download")
def api_download(path: str, _: str = Depends(require_auth)) -> FileResponse:
    target = resolve_path(path)
    if not target.is_file():
        raise HTTPException(404, f"File not found: {target}")
    return FileResponse(str(target), filename=target.name, headers={"X-KaliAccess-SHA256": sha256_file(target)})


@app.get("/api/processes")
def api_processes(_: str = Depends(require_auth)) -> dict:
    rows = []
    for proc in psutil.process_iter(["pid", "name", "username", "memory_info"]):
        try:
            info = proc.info
            rows.append({"pid": info["pid"], "name": info.get("name") or "", "username": info.get("username") or "", "memory": getattr(info.get("memory_info"), "rss", 0)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {"processes": sorted(rows, key=lambda x: (x["name"].lower(), x["pid"]))}


@app.post("/api/processes/{pid}/terminate")
def api_terminate(pid: int, _: str = Depends(require_auth)) -> dict:
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        proc.terminate()
        proc.wait(timeout=5)
        return {"ok": True, "pid": pid, "name": name}
    except psutil.NoSuchProcess:
        raise HTTPException(404, f"Process not found: {pid}")
    except psutil.AccessDenied:
        raise HTTPException(403, f"Access denied for process: {pid}")
    except psutil.TimeoutExpired:
        raise HTTPException(409, f"Process did not stop in time: {pid}")


@app.post("/api/start")
def api_start(payload: StartRequest, _: str = Depends(require_auth)) -> dict:
    return {"ok": True, "pid": start_process(payload.command, payload.cwd)}


def local_addresses() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    values = {"127.0.0.1", "::1"}
    try:
        values.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        pass
    result = []
    for value in values:
        try:
            result.append(ipaddress.ip_address(value))
        except ValueError:
            pass
    return result


def make_tls(cert_path: Path, key_path: Path) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    hostname = socket.gethostname()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    sans: list[x509.GeneralName] = [x509.DNSName(hostname), x509.DNSName("localhost")]
    sans.extend(x509.IPAddress(addr) for addr in local_addresses())
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650)).add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    value = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(value[i:i+2] for i in range(0, len(value), 2))


def configure(username: str, port: int, bind: str, workspace_path: str) -> None:
    password = getpass.getpass("KaliAccess password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters")
    root = Path(workspace_path)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("uploads", "downloads", "scripts", "projects", "results", "logs", "temp"):
        (root / name).mkdir(exist_ok=True)
    cert_path = INSTALL_ROOT / "tls" / "server.crt"
    key_path = INSTALL_ROOT / "tls" / "server.key"
    fingerprint = make_tls(cert_path, key_path)
    config = {
        "username": username,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode("ascii"),
        "host": bind,
        "port": port,
        "workspace": str(root),
        "cert_file": str(cert_path),
        "key_file": str(key_path),
        "max_output_bytes": 2 * 1024 * 1024,
        "max_command_seconds": 300,
    }
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Configured {CONFIG_FILE}")
    print(f"TLS SHA256: {fingerprint}")


def serve() -> None:
    cfg = load_config()
    uvicorn.run(app, host=cfg["host"], port=int(cfg["port"]), ssl_certfile=cfg["cert_file"], ssl_keyfile=cfg["key_file"], access_log=False)


if sys.platform == "win32":
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class KaliAccessService(win32serviceutil.ServiceFramework):
        _svc_name_ = "KaliAccessAgent"
        _svc_display_name_ = "KaliAccess Agent"
        _svc_description_ = "Private remote administration agent for the owner's Windows PC."

        def __init__(self, argv):
            super().__init__(argv)
            self.server = None
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.server is not None:
                self.server.should_exit = True
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            cfg = load_config()
            config = uvicorn.Config(
                app,
                host=cfg["host"],
                port=int(cfg["port"]),
                ssl_certfile=cfg["cert_file"],
                ssl_keyfile=cfg["key_file"],
                access_log=False,
            )
            self.server = uvicorn.Server(config)
            servicemanager.LogInfoMsg("KaliAccessAgent starting")
            self.server.run()
else:
    KaliAccessService = None


def service_command(args: list[str]) -> None:
    if sys.platform != "win32" or KaliAccessService is None:
        raise SystemExit("Windows service mode requires Windows and pywin32")
    sys.argv = [sys.argv[0], *args]
    win32serviceutil.HandleCommandLine(KaliAccessService)


def main() -> None:
    parser = argparse.ArgumentParser(description="KaliAccess Windows Agent")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--username", default=os.environ.get("USERNAME", "sharbel"))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    sub.add_parser("serve")
    p = sub.add_parser("service")
    p.add_argument("service_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "setup":
        configure(args.username, args.port, args.bind, args.workspace)
    elif args.action == "serve":
        serve()
    else:
        service_command(args.service_args)


if __name__ == "__main__":
    main()
