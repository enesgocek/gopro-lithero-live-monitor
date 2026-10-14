# Security and privacy

This project is a local Windows application for one GoPro LIT HERO. It has no
cloud account, telemetry, analytics integration, update service or remote viewer.
Internet access is needed to install dependencies, not to monitor a camera.

## What is stored

- `.connection.json` stores your language, connection preferences, camera Bluetooth
  address/name, Wi-Fi SSID, private camera IP and UDP port. It never stores passwords.
  This file is local and excluded from Git and source releases.
- Windows stores the camera passphrase in a per-user WLAN profile. The application
  uses the native Windows WLAN API in memory; it does not write a plaintext XML file.
- Test photos and video frames are transferred and decoded in memory. Closing the
  viewer releases its pixels. Python/Qt memory release is not forensic secure erasure;
  Windows paging and crash dumps are outside the application's control.
- The camera briefly writes a test JPEG or MP4 to its SD card. Only the uniquely
  identified new test file is deleted. Connection loss or ambiguous media produces
  a warning instead of deleting existing media.
- Diagnostic logs are bounded and held in memory, with credential/device redaction.
  Explicit developer screenshots and benchmark outputs stay in ignored local folders.

## Network boundaries

Camera HTTP is restricted to RFC 1918 / IPv6 ULA addresses, ignores system HTTP
proxies, blocks redirects and limits response/file sizes. The UDP preview listener
binds to the camera-facing local IPv4 interface and filters the sender IP.
IPv4 camera Wi-Fi is the tested streaming path. The camera protocol itself uses
unencrypted, unauthenticated HTTP and UDP: use a trusted camera network and do not
forward its ports to the internet. IP filtering is not cryptographic authentication.

Only GoPro LIT HERO is accepted. A language change does not reconnect or stop an SD
recording. Closing the monitor does not stop an existing recording. Concurrent Quik
or other controllers can interfere; use one controller at a time.

## Local malware boundary

The normal launchers and desktop shortcut use Python `-I -S`: user site packages,
`PYTHONPATH`, `sitecustomize` and executable `.pth` startup hooks are not loaded.
The launcher adds only the interpreter standard library, project source directory and
project-local dependency directory. Qt plugin override variables are cleared and
Windows DLL searching excludes the current working directory and arbitrary PATH
entries. These reduce module/plugin planting; they are not a malware sandbox.

Do not run the monitor as administrator. Keep a functioning antivirus, Windows
updates and firewall enabled. Restrict the local project directory to its owner,
SYSTEM and Administrators if other local accounts use the computer.

Malware running as the same Windows user can access that user's processes, writable
files and credentials. Administrator or SYSTEM malware has broader control. A PIN,
file hash or encrypted preference file cannot reliably isolate this application
after the OS/account is compromised. Stronger separation requires a separate
standard Windows account or a separate trusted computer. These protections do not
claim to make camera footage inaccessible to an already compromised host.

## Reporting a vulnerability

Use this repository's **Security → Report a vulnerability** when private reporting
is enabled. Otherwise open an issue requesting a private reporting channel, without
posting the exploit, credentials, camera identifiers, footage or personal paths.
Do not attach `.connection.json`, WLAN exports, SD media or raw private logs.

## Contributor checks

Run `python tools/release_check.py` before publishing. It verifies the explicit
source allowlist, checks for sensitive file types and scans text for common secret
formats and device identifiers. `--staged` inspects the Git index as well.
Install the supplied local hook with `git config core.hooksPath .githooks`.
CI repeats the release check, regression tests, static analysis and dependency audit.
These are layered safeguards, not a guarantee that no undiscovered flaw exists.
