# KaliAccess

KaliAccess uses two simple Python scripts:

- `windows.py` runs on Windows
- `kali.py` runs on Kali Linux

The scripts automatically exchange the Windows connection information on the local network, so you do not have to manually look up the Windows IP address first.

Remote access itself still uses normal authenticated SSH/SCP/SFTP and Windows Remote Desktop.

## 1. Start Kali first

On Kali:

```bash
git pull
python3 kali.py
```

The script checks that `ssh`, `scp` and `sftp` exist. If they are missing, it offers automatic installation through `openssh-client`.

It then waits for Windows.

You will see something like:

```text
Waiting for windows.py on the local network...
Listening for up to 90 seconds on UDP 45888.
Now run windows.py on the Windows PC.
```

## 2. Run Windows

On the Windows PC:

```powershell
git pull
python windows.py
```

or:

```powershell
py windows.py
```

The first run requests Administrator permission because Windows system services and firewall rules must be configured.

The Windows script automatically:

- installs OpenSSH Server if needed
- installs OpenSSH Client if needed
- starts `sshd`
- sets `sshd` to start automatically with Windows
- opens TCP/22 only to the local subnet
- checks all active IPv4 interfaces
- enables normal authenticated Windows Remote Desktop when the Windows edition supports RDP hosting
- broadcasts only the connection metadata to `kali.py` for 30 seconds

The discovery broadcast contains the Windows hostname, username, local IPv4 addresses and service status. It does not provide command execution.

## 3. Kali receives everything automatically

When discovery succeeds, Kali shows for example:

```text
WINDOWS FOUND

Computer : WINDOWS-PC
Windows  : Windows 11 Pro
User     : sharbel
IP       : 192.168.56.105
SSH      : READY
RDP      : READY
```

`kali.py` automatically tests the received IP addresses and chooses one where TCP port 22 is reachable.

Then you get this menu:

```text
KaliAccess
1) SSH terminal
2) Send file/folder Kali -> Windows
3) Get file Windows -> Kali
4) SFTP
5) Windows screen (RDP)
6) Test SSH connection
7) Show connection info
0) Exit
```

## SSH terminal

Choose:

```text
1
```

This runs:

```bash
ssh WINDOWS_USER@WINDOWS_IP
```

Use your real Windows account password. Windows Hello PIN is not an SSH password.

## Send files to Windows

Choose:

```text
2
```

Enter a Kali file or folder and the script uses `scp`.

Default destination:

```text
Desktop/
```

## Get files from Windows

Choose:

```text
3
```

Example Windows path:

```text
Desktop/test.txt
```

The script downloads it with `scp`.

## SFTP

Choose:

```text
4
```

This opens an interactive SFTP session.

## Windows screen

Choose:

```text
5
```

If Windows supports the built-in RDP host, `kali.py` uses FreeRDP.

If FreeRDP is missing, it can install:

```text
freerdp3-x11
```

Windows Home does not support Microsoft's built-in RDP host, so the script reports that instead of trying to bypass the limitation.

## Background behavior

After `windows.py` finishes:

- OpenSSH keeps running as a normal Windows service
- SSH continues working in the background
- no Python process needs to stay running
- the temporary discovery broadcast stops

Run `windows.py` again whenever you want Kali to automatically rediscover the current Windows address.

## Security

The generated SSH and RDP firewall rules are restricted to the Windows machine's local subnet.

KaliAccess does not create a hidden reverse shell, covert command channel or silent screen-capture agent.

For remote access outside your own LAN, use a private VPN/overlay network rather than exposing SSH or RDP directly to the public Internet.
