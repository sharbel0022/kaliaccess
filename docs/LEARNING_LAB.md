# KaliAccess Malware-Behavior Learning Lab

This lab exists to study malware concepts **without turning KaliAccess into malware**.

The lab deliberately does **not** implement:

- system-wide keylogging
- hidden windows/processes/services
- credential theft
- anti-VM execution gating
- sandbox evasion
- security-product bypass
- covert persistence

Instead it exposes safe, observable equivalents that help you understand what defenders see.

## 1. Keyboard capture concept

KaliAccess already includes a visible key-event test window.

Only events typed inside that window are collected.

Windows:

1. Open **KaliAccess Desktop Helper**
2. Select **Open key-event test**
3. Type test data in the dedicated box

Kali:

```bash
winctl keytest --watch
```

Learning goal:

- understand keyboard event objects
- understand event transport
- inspect timestamps and key names
- distinguish application-local input handling from a global keyboard hook

## 2. Visibility / persistence artifacts

Run:

```bash
winctl lab-visibility
```

This reports the legitimate KaliAccess service and Desktop Helper scheduled task.

Learning goal:

- see where persistent software leaves observable artifacts
- inspect service startup configuration
- inspect scheduled-task state
- understand why hiding or disguising these artifacts is an evasion technique

The lab never tries to hide them.

## 3. Virtualization information

Run:

```bash
winctl lab-environment
```

This reports ordinary Windows system metadata such as:

- system manufacturer
- system model
- BIOS manufacturer/version
- whether Windows reports a hypervisor

Learning goal:

- understand which normal host properties can reveal virtualization
- see why malware sometimes checks environment metadata before executing

KaliAccess does **not** change behavior based on these values.

## 4. Detection exercise

The file:

```text
detections/kaliaccess_lab_sigma.yml
```

contains example Sigma-style rules for identifying KaliAccess installation artifacts in Windows logs.

Useful Windows events to study include:

- System 7045 - new service installed
- Security 4698 - scheduled task created
- PowerShell 4104 - script block logging, when enabled
- Sysmon 1 - process creation, when Sysmon is installed

## 5. Suggested lab

Use a Windows 11 VM and take a snapshot before installation.

1. Enable Windows event logging / Sysmon if desired.
2. Install KaliAccess.
3. Run `winctl lab-environment`.
4. Run `winctl lab-visibility`.
5. Use the visible key-event test.
6. Run screenshots/live view.
7. Inspect Event Viewer or your SIEM.
8. Compare the observed events with the detection examples.

The important distinction is:

```text
learning the observable mechanism       OK
hiding the mechanism from defenders     not part of this lab
```
