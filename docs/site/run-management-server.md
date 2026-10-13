---
title: Server administration
hide:
  - toc
---

<span class="docs-editorial"></span>

Use · Server administration
{: .arch-eyebrow}

# Server administration

For first use, run `micros enroll` from the [Quickstart](get-started.md). Its wizard
can create and start the server, including the browser console. No separate server
setup or frontend build is required. Use this page to manage profiles, configure a
remote host such as a Pi, resolve certificate trust, or stop an existing server.
{: .arch-intro}

## Choose among several servers {#server-profiles}

You can save multiple servers and select a different one for each application.
Interactive `micros enroll` lists their names and addresses **before authentication
or USB access**, then offers to connect to an existing server or create one on this
computer. Press Enter to keep the displayed selected server; mistyped choices
can be corrected in place, and `q` cancels from the setup prompts. Cloudflare login is needed only when the chosen server uses Cloudflare Access.

Connecting to an existing server requires its operator bundle (`client.json`,
`servercert.pem`, `admin.token`), obtained from its operator. A hostname alone does
not grant access. To register and select it directly:

```sh
micros server --profile lab import-client PRIVATE_COPIED_DIRECTORY
micros server list
micros server use lab
micros enroll
```

The choice is stored privately in the application's ignored `.micros/server.json`.
Credentials remain in your user configuration. Later device, deploy and console
commands use that selection. To enroll without the server picker, use
`micros enroll --server lab`; this also saves the choice. Noninteractive enrollment
requires a saved selection, `--server`, or an explicit environment override.

For a new server on this computer, the picker creates an independent identity and
suggests its LAN address and an available HTTPS port, and asks before starting
Docker. It rejects loopback addresses for board enrollment and lets you correct
invalid names, addresses or occupied ports before creating the server. The equivalent commands are:

```sh
micros server --profile lab setup --host SERVER_LAN_IP
micros server --profile lab start
micros server use lab
```

Named local servers use separate Docker Compose project names. Each binds TCP
8443 by default; choose an unused port with `setup --host SERVER_LAN_IP --port 18443`
when another server is running. The chosen port is saved and reused by start,
clients and board enrollment. Remote servers can run simultaneously on their own hosts. Creating a profile does not provision a remote machine.

Profiles live under `$XDG_CONFIG_HOME/micros/servers/NAME` (or
`~/.config/micros/servers/NAME`). The name `default` refers to the original
`micros/server` directory, so existing credentials remain usable.
`MICROS_CLIENT_DIR` overrides all selection; `MICROS_SERVER=lab` selects a named
profile for a command. Unset these overrides before using `server use` or
`enroll --server` to save a different choice.

## Manual setup: prepare the host {#prepare-the-host}

Install the CLI from [Quickstart](get-started.md#install-cli) on a supported macOS
or 64-bit Linux host with OpenSSL and Docker with its Compose plugin. On a
headless Pi, run these commands over SSH after setting PATH as shown in Quickstart.

```sh
micros --help
docker compose version
docker info
```

Docker must be running and accessible to your user. `server start` checks Docker
and Compose before starting the container and explains how to recover if either
is unavailable. Imported operator bundles connect to their existing server;
`server start` requires that server’s private host state. The first start downloads
and builds its container image. ESP32 tools are unnecessary for the console alone.

## Manual setup: choose local or LAN access {#choose-local-or-lan-access}

For a console used **only on this computer**:

```sh
micros server setup --host localhost
MICROS_SERVER_BIND=127.0.0.1 micros server start
```

For a **board, LAN client, or headless Pi**, substitute the server's reachable IP
or hostname:

```sh
micros server setup --host SERVER_LAN_IP
micros server start
```

Clients need access to TCP 8443. `--host` sets the certificate/client address;
it does not assign a static IP or change the listening interfaces. A stable
hostname or DHCP reservation is useful but not required. Repeat the loopback
prefix whenever starting a local-only server.

Setup refuses existing client configuration. For an already configured server,
use `server start` rather than creating a new identity. Expect
`Server ready at https://…:8443`, then check:

```sh
micros server devices
```

An empty roster is normal.

### Where the certificates come from {#generated-certificates}

`micros server setup --host SERVER_LAN_IP` invokes OpenSSL to generate a new
ECDSA P-256 key and a self-signed certificate for that address, valid for one year.
You do not download a private key from the repository or create PEM files manually.
The files belong to this server's private state directory:

| File | Purpose | Sharing |
| --- | --- | --- |
| `servercert.pem` | Public server certificate; clients use it to verify TLS | May be given to clients that should trust this server |
| `prvtkey.pem` | Secret server private key | Keep on the server; include only in protected recovery backups |
| `admin.token` | Secret operator credential, generated alongside the certificate | Give only to authorized operators |
| `enrollments/DEVICE_ID/relay-ca.pem` | Public certificate copied during enrollment for board trust | Contains no private key |

The default location is `~/.config/micros/server/`; a named profile uses
`~/.config/micros/servers/NAME/`. `XDG_CONFIG_HOME`, `--state` and
`MICROS_CLIENT_DIR` can select other locations. `micros server console --trust-info`
prints the selected certificate's exact path and fingerprint. Generated identity
files are not published to GitHub. The PEM files shipped in the SDK's ESP8266
certificate directory are public CA roots, not your server's private key.

Keep this directory when stopping or updating the server. `server start` reuses
its identity; rerunning setup is not a certificate-renewal procedure. Board trust
must be considered before replacing a certificate. Creating it also does not make
it automatically trusted by a browser; follow [console connection](#open-the-console).

### Board certificate trust

Browser trust and board trust are separate. ESP8266 enrollment builds embed the
configured server's public `relay-ca.pem`; the server private key never belongs
on a board. A supplied `enroll --firmware` base must already trust that server.
Changing the server certificate requires rebuilding and installing the matching
base. Standalone ESP8266 builds default to bundled public roots; to target a
private server, build with:

```sh
build/python/bin/python src/micros_tooling/platforms/build_esp8266.py \
  --relay-ca /private/server/servercert.pem --output build/esp8266/private-base
```

For IPv4 server addresses, setup includes both an IP subject alternative name
and an exact DNS-name entry for the pinned ESP8266 TLS library, which only reads
DNS entries. Modern clients still verify the standard IP entry.

MKR WiFi 1010 enrollment automatically installs the selected server profile's
`servercert.pem` bundle into NINA's persistent certificate store, including a
private server certificate generated by setup. TLS verification stays enabled.

This replaces NINA's trust store with that bundle. Enrollment validates the public
certificates and bounds their size before installing Arduino's temporary upload
sketch, then restores the prepared Micros base and saved network settings. The
pinned [Arduino Firmware Uploader](https://arduino.github.io/arduino-fwuploader/2.4/usage/)
is downloaded automatically and its archive checksum is verified.

Keep the board connected until enrollment finishes. If interrupted, rerun
`micros enroll` with the same server and board; the saved receipt retains the
base and settings needed for recovery. If the CLI reports that bootloader entry
failed, double-press Reset and follow its retry instructions.

### Keep a test server separate

The default Docker Compose project is `micros-management`. A different state
directory alone does **not** isolate containers. For a separate test, choose an
unused project name and empty private client directory:

```sh
export MICROS_CLIENT_DIR="$PWD/.micros/test-server"
export MICROS_COMPOSE_PROJECT=micros-consumer-test
micros server setup --host localhost --port 18443
MICROS_SERVER_BIND=127.0.0.1 micros server start
# When finished, with both variables still set:
micros server shutdown
```

`micros server --compose-project micros-consumer-test start` is the equivalent
explicit option; pass the same name to `shutdown`. Names must start with a
lowercase letter or digit and contain only lowercase letters, digits, `_` or `-`.
Check `docker compose ls` and the chosen port first. Project isolation does not
allow two servers to bind the same host port; leave an existing server untouched.

## Open the console {#open-the-console}

A freshly created local server uses a private HTTPS certificate. Your CLI already
trusts the saved certificate; your browser may not. Before opening the console,
show the exact public certificate path and SHA-256 fingerprint:

```sh
micros server console --trust-info
```

If the browser reports an untrusted certificate, compare its host and fingerprint
with this output before adding the saved `servercert.pem` through your browser/OS
certificate manager. This command does not change trust settings. Keep `prvtkey.pem`
and operator tokens private; do not disable TLS checks to connect.

On a computer with the server's operator configuration:

```sh
micros server console
```

This opens `/console/` directly, without a token prompt. Use
`micros server --profile NAME console` (and the same profile with `--trust-info`)
when connecting to a named server.

For a headless Pi, run `micros server console --no-browser` and open the printed
URL on your laptop, or visit `https://SERVER_LAN_IP:8443/console/` directly.
Anyone who can reach the console can manage its boards. Keep it on a trusted
network or protect remote access with Cloudflare Access. CLI and device APIs
still require their respective credentials.

For CLI access from another computer, import the server's operator bundle as
described above. Browser access does not require importing credentials.

Do not run `server setup` on the laptop to connect to an existing server: that
creates another identity. Do not copy the server private key or registry.

## Stop or restart an existing server {#add-a-board-and-stop-the-server}

Keep the server running for network deployment and console access. To deliberately
stop it, run on its host:

```sh
micros server shutdown
```

Shutdown stops the container and retains state. Run `micros server start` on that
host to start it again. After pulling updated server code, `server start` rebuilds
and starts the container. Without `--state` or `--profile`,
selection follows `MICROS_CLIENT_DIR`, `MICROS_SERVER`, the saved selection,
an existing legacy workspace `server/client.json`, then the `default` profile.
Inside an application the saved selection belongs to that project; outside one,
`server use` saves a user selection in `micros/selected-server.json`.
Preserve the server's state directory when moving it. See [private backups](cli.md#private-backups).

| Failure | Fix |
| --- | --- |
| Docker unavailable | Start Docker; check `docker info` permissions. |
| Port occupied | Check the existing listener; create the new server with `setup --port UNUSED_PORT`. |
| Certificate error | Use the configured hostname and establish trust for its matching certificate. |
| Laptop/board cannot connect | Check server address, port binding, firewall, and LAN reachability. |

Frontend/backend development instructions live with the
[server source](../../src/server/README.md). To inspect published service data, see
[Service channels](inspect-service-channels.md).
