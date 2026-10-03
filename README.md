# KaliAccess

KaliAccess is a small Windows setup project that enables secure SSH access from a Kali Linux machine on the same local network.

It gives you:

- SSH terminal access from Kali to Windows
- SCP file transfer in both directions
- SFTP file transfer
- A simple way to generate real SSH/file-transfer traffic for your own security monitoring lab
- A LocalSubnet-only Windows Firewall rule by default

## Easiest setup on Windows

1. Download this repository.
2. Open the folder.
3. Double-click:

```text
START-KALI-ACCESS.bat
```

4. Accept the Windows Administrator prompt.
5. The script prints your Windows username and local IP.

Example:

```text
Windows user : sharbel
Windows IP   : 192.168.1.50
```

## Connect from Kali

```bash
ssh sharbel@192.168.1.50
```

Use your **actual Windows account password**, not your Windows Hello PIN.

## Send a file from Kali to Windows

```bash
scp image.jpg sharbel@192.168.1.50:Desktop/
```

Send a whole folder:

```bash
scp -r myfolder sharbel@192.168.1.50:Desktop/
```

## Download a file from Windows to Kali

```bash
scp sharbel@192.168.1.50:Desktop/file.txt .
```

## SFTP

```bash
sftp sharbel@192.168.1.50
```

Inside SFTP:

```text
ls
cd Desktop
put image.jpg
get file.txt
exit
```

## Disable KaliAccess

Run PowerShell as Administrator:

```powershell
.\disable-kali-access.ps1
```

This stops `sshd`, changes it back to manual startup, and disables the KaliAccess firewall rule.

## Security

KaliAccess intentionally allows SSH only from the Windows machine's **local subnet**.

Do not expose TCP port 22 directly to the public Internet unless you know how to harden and manage SSH securely.

## Security-app testing

For a controlled lab using machines you own, start your monitoring/security application on Windows and then generate normal traffic from Kali:

```bash
ssh USER@WINDOWS_IP
scp testfile.jpg USER@WINDOWS_IP:Desktop/
```

Your monitoring application can then observe normal TCP/SSH traffic such as source/destination addresses, port 22, packet counts and byte counts.
