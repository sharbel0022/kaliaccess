# KaliAccess

KaliAccess is a simple Windows + Kali Linux remote-access lab for computers you own.

The project uses **one Python file**:

```text
kaliaccess.py
```

It configures normal authenticated Windows services instead of a hidden reverse shell.

## What it enables

- SSH terminal access from Kali to Windows
- SCP file transfer in both directions
- SFTP
- OpenSSH running as a Windows background service
- Remote Desktop (RDP) when the Windows edition supports hosting RDP
- Windows Firewall rules limited to the local subnet

## 1. Run on Windows

Clone or download the repository, then run:

```powershell
python kaliaccess.py
```

or:

```powershell
py kaliaccess.py
```

Windows will request Administrator permission once because installing/enabling system services requires it.

When setup finishes, the script prints the Windows username and IPv4 address.

Example:

```text
KALIACCESS READY

Windows edition : Windows 11 Pro
Windows user    : sharbel
Windows IP      : 192.168.1.50
SSH background  : READY
Remote Desktop  : READY
```

After that, the SSH service keeps running in the background. The Python script itself does not need to stay open.

## 2. Terminal from Kali

```bash
ssh sharbel@192.168.1.50
```

Use your actual Windows account password. A Windows Hello PIN is not an SSH password.

## 3. Send a file from Kali to Windows

```bash
scp bild.jpg sharbel@192.168.1.50:Desktop/
```

Send a folder:

```bash
scp -r myfolder sharbel@192.168.1.50:Desktop/
```

## 4. Download a file from Windows to Kali

```bash
scp sharbel@192.168.1.50:Desktop/test.txt .
```

## 5. SFTP

```bash
sftp sharbel@192.168.1.50
```

Example:

```text
cd Desktop
put bild.jpg
get test.txt
exit
```

## 6. Windows screen from Kali

Windows Pro, Enterprise, Education and supported Server editions can host Remote Desktop.

On Kali, install the FreeRDP client if needed:

```bash
sudo apt update
sudo apt install freerdp3-x11 -y
```

Then connect:

```bash
xfreerdp3 /v:192.168.1.50 /u:sharbel /dynamic-resolution
```

Some Kali versions use the older command name:

```bash
xfreerdp /v:192.168.1.50 /u:sharbel /dynamic-resolution
```

Windows Home does not provide the built-in RDP host. KaliAccess will report this instead of trying to bypass that limitation.

## Security

KaliAccess creates firewall rules for SSH and RDP that allow connections only from the Windows computer's local subnet.

It does not create a hidden reverse shell, background command channel, keylogger or silent screen-capture agent.

For access from outside your LAN, use a private VPN/overlay network such as Tailscale rather than forwarding SSH or RDP ports directly from your router.

## Security-app testing

On computers you own, you can run your monitoring application on Windows while generating normal traffic from Kali:

```bash
ssh USER@WINDOWS_IP
scp testfile.jpg USER@WINDOWS_IP:Desktop/
```

This gives you controlled SSH/TCP traffic for observing source/destination addresses, TCP port 22, packet counts and byte counts.
