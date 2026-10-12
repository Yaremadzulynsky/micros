"""USB Wi-Fi provisioning with hidden password entry and persistent device settings."""

import getpass
import ipaddress
import json
from pathlib import Path
import sys
import time
import warnings

from serial.tools import list_ports
from micros_tooling.platforms.esp32.device import Device
from micros_tooling.storage.packages import PackageError, require

# Native USB Espressif, Silicon Labs, WCH and FTDI adapters used by ESP development boards.
USB_VENDORS = {0x303A, 0x10C4, 0x1A86, 0x0403}
TRIAL_TIMEOUT_SECONDS = (
    55  # Firmware trial is 45 seconds; allow USB polling and recovery overhead.
)
SCAN_TIMEOUT_SECONDS = 20  # Firmware scan deadline is 15 seconds.


def select_port(explicit=None, preferred=None):
    if explicit:
        return explicit
    ports = sorted(
        port.device for port in list_ports.comports() if port.vid in USB_VENDORS
    )
    require(
        ports,
        "No ESP USB serial port found. Connect the board, or specify --port PORT.",
    )
    if preferred in ports:
        return preferred  # Caller still verifies the board MAC after connecting.
    require(
        len(ports) == 1,
        "Several USB boards are connected. Select one with --port: " + ", ".join(ports),
    )
    return ports[0]


def validate_credentials(ssid, password):
    require(
        1 <= len(ssid) <= 32 and b"\0" not in ssid,
        "Network name must contain 1–32 UTF-8 bytes without NUL.",
    )
    require(b"\0" not in password, "Password must not contain NUL.")
    require(
        not password
        or 8 <= len(password) <= 63
        or (
            len(password) == 64
            and all(byte in b"0123456789abcdefABCDEF" for byte in password)
        ),
        "Use an 8–63 byte password, a 64-digit hexadecimal key, or --open-network.",
    )


def display_ssid(ssid_hex):
    # repr escapes terminal control characters broadcast by an untrusted access point.
    return repr(bytes.fromhex(ssid_hex).decode("utf-8", errors="replace"))


class Wifi:
    """One physical controller session; password bytes are never included in diagnostics."""

    def __init__(self, port):
        self.device = Device(port)

    def close(self):
        self.device.close()

    def request(self, command):
        # Automatic availability scans can briefly own the radio after USB reset.
        deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
        while True:
            response = self._request(command)
            if response.get("error") != "Wi-Fi operation already in progress":
                require("error" not in response, response.get("error", "Wi-Fi command failed."))
                return response
            require(time.monotonic() < deadline, "Wi-Fi operation already in progress; retry shortly.")
            time.sleep(0.2)

    def _request(self, command):
        try:
            lines = self.device.command(command, "WIFI ", timeout=5)
        except PackageError as error:
            raise PackageError(
                "No valid USB Wi-Fi reply. The port may be busy, the link interrupted, or the base too old. Close other serial clients and retry before migrating firmware."
            ) from error
        try:
            response = json.loads(lines[-1][5:])
        except (ValueError, IndexError) as error:
            raise PackageError(
                "Wi-Fi reply was interrupted over USB. Run ./micros wifi status to check the result."
            ) from error
        return response

    def status(self):
        return self.request("WIFI STATUS")

    def settled_status(self, timeout=10):
        """Allow USB-reset reconnection to finish before presenting a diagnostic snapshot."""
        deadline = time.monotonic() + timeout
        result = self.status()
        while (
            result["state"] in ("connecting", "waiting_for_ip")
            and time.monotonic() < deadline
        ):
            time.sleep(0.5)
            result = self.status()
        return result

    def scan(self):
        result = self.request("WIFI SCAN")
        deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
        while result["scan"] == "scanning" and time.monotonic() < deadline:
            time.sleep(0.5)
            result = self.status()
        require(
            result["scan"] == "ready",
            "Wi-Fi scan did not finish. Try again, or supply --ssid NAME.",
        )
        return result["networks"]

    def saved_networks(self):
        return self.request("WIFI LIST")["saved_networks"]

    def save(self, ssid, password, fallback=False):
        validate_credentials(ssid, password)
        command = "WIFI FALLBACK " if fallback else "WIFI ADD "
        return self.request(command + ssid.hex() + " " + (password.hex() or "-"))

    def forget(self, ssid):
        validate_credentials(ssid, b"")
        return self.request("WIFI FORGET " + ssid.hex())

    def configure(self, ssid, password, progress=lambda message: None):
        validate_credentials(ssid, password)
        deadline = time.monotonic() + TRIAL_TIMEOUT_SECONDS
        try:
            result = self.request(
                "WIFI SET " + ssid.hex() + " " + (password.hex() or "-")
            )
            previous_state = None
            while result["testing"] and time.monotonic() < deadline:
                state = (result["state"], result["reason"])
                if state != previous_state:
                    progress(
                        "Connecting… "
                        + state[0].replace("_", " ")
                        + (
                            ": " + state[1].replace("_", " ")
                            if state[1] != "connection_pending"
                            else ""
                        )
                    )
                    previous_state = state
                time.sleep(0.5)
                result = self.status()
            require(
                not result["testing"],
                "Connection test is still pending. Run ./micros wifi status over USB.",
            )
            require(
                result["result"] == "saved" and result["state"] == "connected",
                "Wi-Fi setup failed ("
                + result["reason"].replace("_", " ")
                + "). Previous saved settings were retained.",
            )
            ipaddress.IPv4Address(result["ip"])
            return result
        except KeyboardInterrupt:
            try:
                self.request("WIFI CANCEL")
            except (OSError, ValueError):
                pass  # Device also restores the previous settings at its own trial deadline.
            raise


def prompt_network_name(progress):
    while True:
        # Spaces are part of an SSID, including at the beginning and end.
        ssid = input("2.4 GHz Wi-Fi network name: ").encode("utf-8")
        try:
            validate_credentials(ssid, b"")
            return ssid
        except PackageError as error:
            progress(str(error))


def credentials_from_terminal(ssid, args, progress, *, open_network=None):
    """Validate before USB writes; retry only credentials entered interactively."""
    validate_credentials(ssid, b"")
    if args.password_file:
        with Path(args.password_file).open("rb") as stream:
            password = stream.read(67)
        require(len(password) <= 66, "Password file exceeds the Wi-Fi credential limit.")
        password = password.removesuffix(b"\n").removesuffix(b"\r")
        require(password, "Password file is empty. For an open network, use --open-network explicitly.")
        validate_credentials(ssid, password)
        return ssid, password
    selected_open = args.open_network if open_network is None else open_network
    if selected_open:
        return ssid, b""
    require(
        not getattr(args, "json", False) and sys.stdin.isatty(),
        "Password entry needs a terminal. Use --password-file PATH for automation.",
    )
    while True:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Wi-Fi password: ").encode("utf-8")
        except getpass.GetPassWarning as error:
            raise PackageError(
                "This terminal cannot hide password entry. Use --password-file PATH."
            ) from error
        try:
            require(password, "For an open network, use --open-network explicitly.")
            validate_credentials(ssid, password)
            return ssid, password
        except PackageError as error:
            progress(str(error))


def setup_from_terminal(wifi, args, progress):
    require(
        not getattr(args, "json", False)
        or (args.ssid is not None and (args.password_file or args.open_network)),
        "JSON setup needs --ssid and either --password-file or --open-network.",
    )
    selected_open = args.open_network
    if args.ssid is not None:
        ssid = args.ssid.encode("utf-8")
        validate_credentials(ssid, b"")
    else:
        require(
            sys.stdin.isatty(),
            "Interactive setup needs a terminal. For automation use --ssid with --password-file or --open-network.",
        )
        progress("Scanning nearby Wi-Fi networks…")
        networks = wifi.scan()
        unique = {}
        for network in networks:
            if network["ssid_hex"]:
                unique.setdefault(network["ssid_hex"], network)
        networks = list(unique.values())
        for index, network in enumerate(networks, 1):
            progress(
                f"{index}. {display_ssid(network['ssid_hex'])} · {network['rssi']} dBm"
                + (" · open" if network["open"] else "")
            )
        progress("0. Enter a network name manually")
        while True:
            choice = input("Select network: ").strip()
            if choice.isdecimal() and 0 <= int(choice) <= len(networks):
                break
            progress("Choose a displayed network number; Ctrl-C cancels.")
        if int(choice) == 0:
            ssid = prompt_network_name(progress)
        else:
            selected = networks[int(choice) - 1]
            ssid = bytes.fromhex(selected["ssid_hex"])
            selected_open = selected["open"]
    ssid, password = credentials_from_terminal(ssid, args, progress, open_network=selected_open)
    if getattr(args, "wifi_action", None) == "add":
        return wifi.save(ssid, password, getattr(args, "fallback", False))
    return wifi.configure(ssid, password, progress)
