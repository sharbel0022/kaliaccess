import json
import os
import shutil
import socket
import subprocess
import time

DISCOVERY_PORT = 45888
DISCOVERY_MAGIC = "KALIACCESS_V1"


def command_exists(name):
    return shutil.which(name) is not None


def ensure_ssh_tools():
    missing = [name for name in ("ssh", "scp", "sftp") if not command_exists(name)]
    if not missing:
        return True

    print("OpenSSH client tools are missing:", ", ".join(missing))
    print("Installing openssh-client...")

    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "openssh-client"],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("Could not install openssh-client automatically.")
        return False

    return all(command_exists(name) for name in ("ssh", "scp", "sftp"))


def wait_for_windows(timeout=90):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", DISCOVERY_PORT))
    sock.settimeout(1.0)

    print()
    print("Waiting for windows.py on the local network...")
    print(f"Listening for up to {timeout} seconds on UDP {DISCOVERY_PORT}.")
    print("Now run windows.py on the Windows PC.")
    print()

    end = time.time() + timeout

    while time.time() < end:
        try:
            data, sender = sock.recvfrom(65535)
        except socket.timeout:
            continue

        try:
            packet = json.loads(data.decode("utf-8"))
        except Exception:
            continue

        if packet.get("magic") != DISCOVERY_MAGIC:
            continue

        sock.close()
        packet["detected_ip"] = sender[0]
        return packet

    sock.close()
    return None


def tcp_test(ip, port, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def select_ip(packet):
    candidates = []

    sender_ip = packet.get("detected_ip")
    if sender_ip:
        candidates.append(sender_ip)

    for ip in packet.get("ips", []):
        if ip not in candidates:
            candidates.append(ip)

    print("Testing SSH addresses...")

    for ip in candidates:
        if tcp_test(ip, int(packet.get("ssh_port", 22))):
            print(f"  {ip}:22 -> reachable")
            return ip
        print(f"  {ip}:22 -> not reachable")

    return sender_ip or (candidates[0] if candidates else None)


def run_ssh(user, ip):
    subprocess.run(["ssh", f"{user}@{ip}"])


def send_file(user, ip):
    local_path = input("Local file/folder on Kali: ").strip()
    if not local_path:
        return

    local_path = os.path.expanduser(local_path)

    if not os.path.exists(local_path):
        print("That local path does not exist.")
        return

    remote_path = input("Windows destination [Desktop/]: ").strip() or "Desktop/"

    cmd = ["scp"]
    if os.path.isdir(local_path):
        cmd.append("-r")

    cmd.extend([local_path, f"{user}@{ip}:{remote_path}"])
    subprocess.run(cmd)


def get_file(user, ip):
    remote_path = input("Windows path, e.g. Desktop/test.txt: ").strip()
    if not remote_path:
        return

    local_path = input("Save on Kali [current folder]: ").strip() or "."
    subprocess.run(["scp", f"{user}@{ip}:{remote_path}", local_path])


def run_sftp(user, ip):
    subprocess.run(["sftp", f"{user}@{ip}"])


def ensure_freerdp():
    for cmd in ("xfreerdp3", "xfreerdp"):
        if command_exists(cmd):
            return cmd

    print("FreeRDP is not installed.")
    answer = input("Install freerdp3-x11 now? [y/N]: ").strip().lower()

    if answer != "y":
        return None

    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "freerdp3-x11"],
            check=True,
        )
    except subprocess.CalledProcessError:
        print("Could not install FreeRDP automatically.")
        return None

    for cmd in ("xfreerdp3", "xfreerdp"):
        if command_exists(cmd):
            return cmd

    return None


def open_screen(user, ip, packet):
    if not packet.get("rdp_supported"):
        print("This Windows edition does not support the built-in RDP host.")
        return

    if not packet.get("rdp_ready"):
        print("Windows reported that Remote Desktop is not ready.")
        return

    cmd = ensure_freerdp()
    if not cmd:
        return

    subprocess.run(
        [
            cmd,
            f"/v:{ip}",
            f"/u:{user}",
            "/dynamic-resolution",
            "+clipboard",
        ]
    )


def show_info(packet, ip):
    print()
    print("=" * 58)
    print("WINDOWS FOUND")
    print("=" * 58)
    print(f"Computer : {packet.get('hostname', '?')}")
    print(f"Windows  : {packet.get('windows_product', '?')}")
    print(f"User     : {packet.get('username', '?')}")
    print(f"IP       : {ip or '?'}")
    print(f"SSH      : {'READY' if packet.get('ssh_ready') else 'NOT READY'}")

    if packet.get("rdp_ready"):
        rdp_text = "READY"
    elif packet.get("rdp_supported"):
        rdp_text = "SUPPORTED BUT NOT READY"
    else:
        rdp_text = "NOT SUPPORTED"

    print(f"RDP      : {rdp_text}")
    print("=" * 58)


def menu(packet, ip):
    user = packet.get("username")

    if not user or not ip:
        print("Missing Windows username or IP.")
        return 1

    while True:
        print()
        print("KaliAccess")
        print("1) SSH terminal")
        print("2) Send file/folder Kali -> Windows")
        print("3) Get file Windows -> Kali")
        print("4) SFTP")
        print("5) Windows screen (RDP)")
        print("6) Test SSH connection")
        print("7) Show connection info")
        print("0) Exit")

        choice = input("> ").strip()

        if choice == "1":
            run_ssh(user, ip)
        elif choice == "2":
            send_file(user, ip)
        elif choice == "3":
            get_file(user, ip)
        elif choice == "4":
            run_sftp(user, ip)
        elif choice == "5":
            open_screen(user, ip, packet)
        elif choice == "6":
            if tcp_test(ip, 22):
                print(f"SSH is reachable at {ip}:22")
            else:
                print(f"SSH is NOT reachable at {ip}:22")
        elif choice == "7":
            show_info(packet, ip)
        elif choice == "0":
            return 0
        else:
            print("Choose 0-7.")


def manual_mode():
    print()
    print("Automatic discovery timed out.")
    answer = input("Enter Windows IP manually? [y/N]: ").strip().lower()

    if answer != "y":
        return None

    ip = input("Windows IP: ").strip()
    user = input("Windows username: ").strip()

    if not ip or not user:
        return None

    return {
        "magic": DISCOVERY_MAGIC,
        "hostname": "manual",
        "username": user,
        "ips": [ip],
        "detected_ip": ip,
        "ssh_port": 22,
        "ssh_ready": tcp_test(ip, 22),
        "rdp_supported": True,
        "rdp_ready": False,
        "windows_product": "Windows",
    }


def main():
    if os.name == "nt":
        print("Run kali.py on Kali/Linux, not Windows.")
        return 1

    if not ensure_ssh_tools():
        return 1

    packet = wait_for_windows(timeout=90)

    if packet is None:
        packet = manual_mode()
        if packet is None:
            return 1

    ip = select_ip(packet)
    show_info(packet, ip)

    if not ip or not packet.get("ssh_ready") or not tcp_test(ip, 22):
        print()
        print("Windows was discovered, but SSH port 22 is not reachable.")
        print("Run windows.py again and check the SSH status it prints.")
        return 1

    print()
    print("Use your normal Windows account password when SSH asks for it.")
    print("Windows Hello PIN is not an SSH password.")

    return menu(packet, ip)


if __name__ == "__main__":
    raise SystemExit(main())
