# KaliAccess

KaliAccess ar ett enkelt testprojekt for Windows + Kali Linux.

Projektet bestar av **en Python-fil**:

```text
kaliaccess.py
```

Nar du kor filen pa Windows:

- OpenSSH Server installeras om det saknas
- SSH-tjansten startas
- SSH startar automatiskt med Windows
- Windows Firewall tillater TCP/22 fran det lokala natverket
- ditt Windows-anvandarnamn och din lokala IP visas

## 1. Kor pa Windows

Du behover Python installerat.

Oppna PowerShell i projektmappen:

```powershell
python kaliaccess.py
```

Windows kommer att be om administratorrattigheter.

Nar allt ar klart visas exempelvis:

```text
KALIACCESS AR KLAR

Windows user: sharbel
Windows IP:   192.168.1.50
```

## 2. Anslut fran Kali

```bash
ssh sharbel@192.168.1.50
```

Anvand ditt riktiga Windows-kontolosenord, inte Windows Hello-PIN.

## 3. Skicka en bild Kali -> Windows

```bash
scp bild.jpg sharbel@192.168.1.50:Desktop/
```

## 4. Hamta en fil Windows -> Kali

```bash
scp sharbel@192.168.1.50:Desktop/test.txt .
```

## 5. SFTP

```bash
sftp sharbel@192.168.1.50
```

Exempel inne i SFTP:

```text
cd Desktop
put bild.jpg
get test.txt
exit
```

## Security-labb

Pa datorer du sjalv ager kan du kora din security-app pa Windows samtidigt och sedan skapa normal SSH/SCP-trafik fran Kali. Da kan appen observera bland annat TCP-port 22, IP-adresser, paket och datamangd.

KaliAccess begransar brandvaggsregeln till det lokala natverket och oppnar inte SSH direkt mot Internet.
