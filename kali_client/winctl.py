#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import ssl
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.table import Table

VERSION = "1.2.0"
CONFIG_DIR = Path.home() / ".config" / "kaliaccess"
CONFIG_FILE = CONFIG_DIR / "config.json"
CERT_FILE = CONFIG_DIR / "windows-agent.crt"
console = Console()


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise SystemExit("KaliAccess is not configured. Run: winctl setup <WINDOWS-IP>")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def fingerprint(pem: str) -> str:
    der = ssl.PEM_cert_to_DER_cert(pem)
    value = hashlib.sha256(der).hexdigest().upper()
    return ":".join(value[i : i + 2] for i in range(0, len(value), 2))


def setup(args: argparse.Namespace) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        pem = ssl.get_server_certificate((args.host, args.port))
    except OSError as exc:
        raise SystemExit(f"Could not reach KaliAccess Agent: {exc}")

    fp = fingerprint(pem)
    console.print(f"TLS certificate SHA256: [bold]{fp}[/bold]")
    if not args.yes:
        answer = input("Trust this Windows PC certificate? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            raise SystemExit("Setup cancelled")

    CERT_FILE.write_text(pem, encoding="ascii")
    config = {
        "host": args.host,
        "port": args.port,
        "username": args.username,
        "cert_file": str(CERT_FILE),
    }
    save_config(config)
    password = getpass.getpass("KaliAccess password: ")
    client = Client(config, password)
    data = client.get("/api/ping")
    console.print(f"[green]Connected[/green] to {data['hostname']} (agent {data['version']})")


class PinnedCertificateAdapter(HTTPAdapter):
    """Trust one saved server certificate while allowing the PC IP to change."""

    def __init__(self, cert_file: str):
        self.cert_file = cert_file
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context(cafile=self.cert_file)
        context.check_hostname = False
        pool_kwargs["ssl_context"] = context
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


class Client:
    def __init__(self, config: dict[str, Any], password: str):
        self.config = config
        self.password = password
        self.base = f"https://{config['host']}:{config['port']}"
        self.auth = (config["username"], password)
        self.session = requests.Session()
        self.session.mount("https://", PinnedCertificateAdapter(config["cert_file"]))

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = self.session.request(
                method,
                self.base + path,
                auth=self.auth,
                timeout=kwargs.pop("timeout", 90),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise SystemExit(f"Connection failed: {exc}")
        if response.status_code == 401:
            raise SystemExit("Authentication failed")
        if not response.ok:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise SystemExit(f"Agent error {response.status_code}: {detail}")
        return response

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs).json()

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs).json()


def new_client() -> Client:
    config = load_config()
    password = os.environ.get("KALIACCESS_PASSWORD") or getpass.getpass("KaliAccess password: ")
    return Client(config, password)


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def human_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def show_status(client: Client) -> None:
    data = client.get("/api/status")
    console.print(f"[bold green]{data['hostname']} ONLINE[/bold green]")
    table = Table(show_header=False)
    rows = [
        ("User", data["user"]),
        ("Windows", data["windows"]),
        ("CPU", f"{data['cpu_percent']:.1f}%"),
        ("RAM", f"{human_bytes(data['ram_used'])} / {human_bytes(data['ram_total'])}"),
        ("Disk", f"{human_bytes(data['disk_used'])} / {human_bytes(data['disk_total'])}"),
        ("Uptime", human_uptime(data["uptime_seconds"])),
        ("Workspace", data["workspace"]),
        ("WSL", "available" if data["wsl_available"] else "not found"),
        ("Python", "available" if data["python_available"] else "not found"),
        ("Agent", data["agent_version"]),
    ]
    for key, value in rows:
        table.add_row(key, str(value))
    console.print(table)


def run_remote(client: Client, command: str, shell: str, cwd: str | None, timeout: int = 60) -> dict:
    data = client.post(
        "/api/run",
        json={"command": command, "shell": shell, "cwd": cwd, "timeout": timeout},
        timeout=timeout + 15,
    )
    if data.get("stdout"):
        print(data["stdout"])
    if data.get("stderr"):
        print(data["stderr"], file=sys.stderr)
    return data


def interactive_shell(client: Client, shell: str) -> None:
    cwd = None
    console.print(f"KaliAccess {shell} shell. Type [bold]exit[/bold] to leave.")
    while True:
        prompt = f"{shell}:{cwd or '~'}> "
        try:
            command = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if command.strip().lower() in {"exit", "quit"}:
            return
        if not command.strip():
            continue
        data = run_remote(client, command, shell, cwd)
        cwd = data.get("cwd") or cwd


def upload(client: Client, source: str, destination: str | None) -> None:
    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    with path.open("rb") as handle:
        files = {"file": (path.name, handle, "application/octet-stream")}
        data = {"destination": destination} if destination else {}
        response = client.request("POST", "/api/files/upload", files=files, data=data, timeout=3600)
    result = response.json()
    local_hash = digest.hexdigest()
    if result["sha256"].lower() != local_hash.lower():
        raise SystemExit("Upload completed but SHA-256 verification FAILED")
    console.print(f"[green]Uploaded[/green] {path} -> {result['path']} ({human_bytes(result['bytes'])})")
    console.print(f"SHA256 {result['sha256']}")


def download(client: Client, remote: str, output: str | None) -> None:
    params = {"path": remote}
    response = client.request("GET", "/api/files/download", params=params, stream=True, timeout=3600)
    target = Path(output or Path(remote.replace("\\", "/")).name)
    if target.is_dir():
        disposition = response.headers.get("content-disposition", "")
        filename = Path(remote.replace("\\", "/")).name
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip('"')
        target = target / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with target.open("wb") as handle:
        for chunk in response.iter_content(1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)
            digest.update(chunk)
    expected = response.headers.get("X-KaliAccess-SHA256")
    if expected and expected.lower() != digest.hexdigest().lower():
        target.unlink(missing_ok=True)
        raise SystemExit("Download SHA-256 verification FAILED; incomplete file removed")
    console.print(f"[green]Downloaded[/green] {remote} -> {target}")
    console.print(f"SHA256 {digest.hexdigest()}")


def list_remote(client: Client, path: str | None) -> None:
    response = client.request("GET", "/api/files/list", params={"path": path} if path else {})
    data = response.json()
    console.print(f"[bold]{data['path']}[/bold]")
    table = Table("Type", "Name", "Size")
    for item in data["entries"]:
        table.add_row("DIR" if item["is_dir"] else "FILE", item["name"], "" if item["is_dir"] else human_bytes(item["size"] or 0))
    console.print(table)


def process_list(client: Client) -> None:
    data = client.get("/api/processes")
    table = Table("PID", "Name", "User", "RAM")
    for item in data["processes"]:
        table.add_row(str(item["pid"]), item["name"], item["username"], human_bytes(item["memory"] or 0))
    console.print(table)


def show_desktop_status(client: Client) -> None:
    data = client.get("/api/desktop/status")
    console.print(f"[green]Desktop helper ONLINE[/green] user={data['user']} session={data['session']} version={data['version']}")
    console.print(f"Key-event test buffer: {data['keytest_events']} event(s)")


def save_screenshot(client: Client, output: str | None) -> Path:
    response = client.request("GET", "/api/desktop/screenshot", timeout=20)
    if response.headers.get("content-type", "").split(";", 1)[0].lower() != "image/png":
        raise SystemExit("Desktop helper did not return a PNG image")
    target = Path(output) if output else Path(f"kaliaccess-screen-{time.strftime('%Y%m%d-%H%M%S')}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    console.print(f"[green]Screenshot saved[/green] {target.resolve()}")
    return target


def live_screen(client: Client, interval: float) -> None:
    interval_ms = max(250, int(interval * 1000))

    class ScreenHandler(BaseHTTPRequestHandler):
        def log_message(self, _format, *args):
            return

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>KaliAccess Live Screen</title>
<style>
html,body{{margin:0;background:#111;color:#eee;font-family:sans-serif;height:100%;}}
main{{display:flex;flex-direction:column;height:100%;}}
header{{padding:10px 14px;background:#1b1b1b;}}
img{{display:block;max-width:100%;max-height:calc(100vh - 46px);margin:auto;object-fit:contain;}}
</style>
</head>
<body>
<main>
<header>KaliAccess live screen - read-only view</header>
<img id="screen" src="/frame">
</main>
<script>
const img=document.getElementById('screen');
setInterval(()=>{{img.src='/frame?t='+Date.now();}}, {interval_ms});
</script>
</body>
</html>""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html)
                return

            if self.path.startswith("/frame"):
                try:
                    response = client.request("GET", "/api/desktop/screenshot", timeout=20)
                    body = response.content
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                except SystemExit as exc:
                    body = str(exc).encode("utf-8", errors="replace")
                    self.send_response(502)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                return

            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ScreenHandler)
    url = f"http://127.0.0.1:{server.server_port}/"
    console.print(f"[green]Live screen viewer[/green] {url}")
    console.print("Read-only view. Press Ctrl+C here to stop it.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def show_keytest(client: Client, limit: int, watch: bool) -> None:
    console.print("[yellow]Safe test mode:[/yellow] only keys typed in the visible Windows KaliAccess key-event test window are available.")
    seen: set[tuple[str, str, str]] = set()

    def fetch() -> list[dict]:
        return client.request("GET", "/api/keytest/events", params={"limit": limit}).json()["events"]

    if not watch:
        rows = fetch()
        table = Table("Time", "Key", "Character")
        for item in rows:
            table.add_row(item.get("time", ""), item.get("keysym", ""), item.get("char", ""))
        console.print(table)
        return

    console.print("Watching for new test events. Press Ctrl+C to stop.")
    try:
        while True:
            for item in fetch():
                key = (item.get("time", ""), item.get("keysym", ""), item.get("char", ""))
                if key in seen:
                    continue
                seen.add(key)
                console.print(f"{key[0]}  key={key[1]!r} char={key[2]!r}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print()


def show_audit(client: Client, limit: int) -> None:
    rows = client.request("GET", "/api/logs/audit", params={"limit": limit}).json()["events"]
    table = Table("Time", "Method", "Path", "Status", "Client", "ms")
    for item in rows:
        table.add_row(
            str(item.get("time", "")),
            str(item.get("method", "")),
            str(item.get("path", "")),
            str(item.get("status", "")),
            str(item.get("client", "")),
            str(item.get("duration_ms", "")),
        )
    console.print(table)


def show_lab_environment(client: Client) -> None:
    data = client.get("/api/lab/environment")
    table = Table("Field", "Value")
    fields = [
        ("Computer", data.get("ComputerName", "")),
        ("Manufacturer", data.get("Manufacturer", "")),
        ("Model", data.get("Model", "")),
        ("BIOS manufacturer", data.get("BIOSManufacturer", "")),
        ("BIOS version", data.get("BIOSVersion", "")),
        ("Hypervisor present", data.get("HypervisorPresent", "")),
    ]
    for key, value in fields:
        table.add_row(key, str(value))
    console.print(table)
    console.print(f"[yellow]{data.get('note', '')}[/yellow]")


def show_lab_visibility(client: Client) -> None:
    data = client.get("/api/lab/visibility")
    console.print("[bold]KaliAccess persistence/visibility artifacts[/bold]")
    service = data.get("Service")
    task = data.get("DesktopHelperTask")
    table = Table("Artifact", "Name", "State", "Details")
    if service:
        table.add_row(
            "Windows service",
            str(service.get("Name", "")),
            str(service.get("State", "")),
            f"StartMode={service.get('StartMode', '')} Path={service.get('PathName', '')}",
        )
    else:
        table.add_row("Windows service", "KaliAccessAgent", "not found", "")
    if task:
        table.add_row(
            "Scheduled task",
            str(task.get("TaskName", "")),
            str(task.get("State", "")),
            str(task.get("TaskPath", "")),
        )
    else:
        table.add_row("Scheduled task", "KaliAccess Desktop Helper", "not found", "")
    console.print(table)
    console.print(f"[yellow]{data.get('note', '')}[/yellow]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="winctl", description="Control your Windows PC from Kali using KaliAccess")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("setup", help="Trust and configure a Windows KaliAccess Agent")
    p.add_argument("host")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--username", default="sharbel")
    p.add_argument("-y", "--yes", action="store_true", help="Trust the first certificate without confirmation")

    sub.add_parser("ping")
    sub.add_parser("status")
    sub.add_parser("desktop-status", help="Check the signed-in Windows desktop helper")

    p = sub.add_parser("screenshot", help="Capture the signed-in Windows desktop")
    p.add_argument("output", nargs="?")

    p = sub.add_parser("screen", help="Open a read-only live screen viewer in your Kali browser")
    p.add_argument("--interval", type=float, default=0.8, help="Refresh interval in seconds (minimum 0.25)")

    p = sub.add_parser("keytest", help="Read events from the visible Windows key-event test window")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--watch", action="store_true")

    p = sub.add_parser("logs", help="Show recent authenticated agent audit events")
    p.add_argument("--limit", type=int, default=100)

    sub.add_parser("lab-environment", help="Show ordinary Windows virtualization/environment metadata without evasion")
    sub.add_parser("lab-visibility", help="Show KaliAccess service/task artifacts for defensive learning")

    p = sub.add_parser("run")
    p.add_argument("command")
    p.add_argument("--shell", choices=["powershell", "cmd", "wsl"], default="powershell")
    p.add_argument("--cwd")
    p.add_argument("--timeout", type=int, default=60)

    p = sub.add_parser("shell")
    p.add_argument("shell", nargs="?", choices=["powershell", "cmd", "wsl"], default="powershell")

    p = sub.add_parser("upload")
    p.add_argument("source")
    p.add_argument("destination", nargs="?")

    p = sub.add_parser("download")
    p.add_argument("remote")
    p.add_argument("output", nargs="?")

    p = sub.add_parser("ls")
    p.add_argument("path", nargs="?")

    p = sub.add_parser("mkdir")
    p.add_argument("path")

    sub.add_parser("ps")

    p = sub.add_parser("kill")
    p.add_argument("pid", type=int)

    p = sub.add_parser("start")
    p.add_argument("command")
    p.add_argument("--cwd")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.action == "setup":
        setup(args)
        return

    client = new_client()
    if args.action == "ping":
        data = client.get("/api/ping")
        console.print(f"[green]ONLINE[/green] {data['hostname']} agent={data['version']}")
    elif args.action == "status":
        show_status(client)
    elif args.action == "desktop-status":
        show_desktop_status(client)
    elif args.action == "screenshot":
        save_screenshot(client, args.output)
    elif args.action == "screen":
        live_screen(client, args.interval)
    elif args.action == "keytest":
        show_keytest(client, max(1, min(args.limit, 500)), args.watch)
    elif args.action == "logs":
        show_audit(client, max(1, min(args.limit, 1000)))
    elif args.action == "lab-environment":
        show_lab_environment(client)
    elif args.action == "lab-visibility":
        show_lab_visibility(client)
    elif args.action == "run":
        data = run_remote(client, args.command, args.shell, args.cwd, args.timeout)
        raise SystemExit(data.get("exit_code", 0))
    elif args.action == "shell":
        interactive_shell(client, args.shell)
    elif args.action == "upload":
        upload(client, args.source, args.destination)
    elif args.action == "download":
        download(client, args.remote, args.output)
    elif args.action == "ls":
        list_remote(client, args.path)
    elif args.action == "mkdir":
        data = client.post("/api/files/mkdir", json={"path": args.path, "parents": True})
        console.print(f"[green]Created[/green] {data['path']}")
    elif args.action == "ps":
        process_list(client)
    elif args.action == "kill":
        data = client.post(f"/api/processes/{args.pid}/terminate")
        console.print(f"[green]Stopped[/green] {data['name']} ({data['pid']})")
    elif args.action == "start":
        data = client.post("/api/start", json={"command": args.command, "cwd": args.cwd})
        console.print(f"[green]Started[/green] PID {data['pid']}")


if __name__ == "__main__":
    main()
