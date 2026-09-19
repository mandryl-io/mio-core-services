"""Drive WiFi through nmcli. Parsing stays here so tests never need a radio."""

from __future__ import annotations

from dataclasses import dataclass

from mio_core_services.wifi import (
    HOTSPOT_CONNECTION,
    HOTSPOT_PASSWORD,
    HOTSPOT_SSID,
    WIFI_DEVICE,
)


class RadioError(Exception):
    """nmcli refused the request, timed out, or is not installed."""


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int
    security: str


def split_nmcli(line: str) -> list[str]:
    """Split one `nmcli -t` row. Colons in values are escaped as `\\:`."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def parse_wifi_list(text: str) -> list[Network]:
    """Keep the strongest copy of each SSID. Hidden (empty) names are dropped."""
    best: dict[str, Network] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = split_nmcli(line)
        if len(fields) < 2:
            continue
        ssid = fields[0].strip()
        if not ssid:
            continue
        try:
            signal = int(fields[1])
        except ValueError:
            signal = 0
        security = fields[2].strip() if len(fields) > 2 else ""
        previous = best.get(ssid)
        if previous is None or signal > previous.signal:
            best[ssid] = Network(ssid=ssid, signal=signal, security=security)
    return sorted(best.values(), key=lambda net: (-net.signal, net.ssid.lower()))


def parse_device_show(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def has_ipv4(fields: dict[str, str]) -> bool:
    return any(
        key.startswith("IP4.ADDRESS") and bool(value)
        for key, value in fields.items()
    )


def active_connection(fields: dict[str, str]) -> str:
    return fields.get("GENERAL.CONNECTION", "").strip()


def is_home_connected(
    fields: dict[str, str],
    connectivity: str,
    hotspot_connection: str = HOTSPOT_CONNECTION,
) -> bool:
    """True when wlan0 is a client with an IPv4 address, not the setup AP."""
    connection = active_connection(fields)
    if not connection or connection == hotspot_connection or connection == "--":
        return False
    if not has_ipv4(fields):
        return False
    return connectivity.strip().lower() != "none"


def parse_connect_body(payload: dict) -> tuple[str, str]:
    ssid = payload.get("ssid")
    password = payload.get("password", "")
    if not isinstance(ssid, str) or not ssid.strip():
        raise ValueError("Choose a network.")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ValueError("Password must be text.")
    return ssid.strip(), password


class Radio:
    """Thin nmcli wrapper. Pass `run` in tests to avoid a real subprocess."""

    def __init__(
        self,
        run=None,
        device: str = WIFI_DEVICE,
        hotspot_ssid: str = HOTSPOT_SSID,
        hotspot_password: str = HOTSPOT_PASSWORD,
        hotspot_connection: str = HOTSPOT_CONNECTION,
    ) -> None:
        self._run = run or _nmcli
        self.device = device
        self.hotspot_ssid = hotspot_ssid
        self.hotspot_password = hotspot_password
        self.hotspot_connection = hotspot_connection

    def connectivity(self) -> str:
        try:
            return self._run("networking", "connectivity").strip() or "none"
        except RadioError:
            return "none"

    def device_fields(self) -> dict[str, str]:
        try:
            text = self._run("-t", "device", "show", self.device)
        except RadioError:
            return {}
        return parse_device_show(text)

    def is_home_connected(self) -> bool:
        return is_home_connected(
            self.device_fields(),
            self.connectivity(),
            hotspot_connection=self.hotspot_connection,
        )

    def active_ssid(self) -> str | None:
        fields = self.device_fields()
        connection = active_connection(fields)
        if not connection or connection == "--":
            return None
        if connection == self.hotspot_connection:
            return self.hotspot_ssid
        try:
            ssid = self._run(
                "-t", "-f", "802-11-wireless.ssid", "connection", "show", connection
            ).strip()
        except RadioError:
            return connection
        return ssid or connection

    def scan(self) -> list[Network]:
        args = (
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            self.device,
        )
        try:
            text = self._run(*args, "--rescan", "yes", timeout=25)
        except RadioError:
            text = self._run(*args, timeout=15)
        return parse_wifi_list(text)

    def wifi_on(self) -> None:
        try:
            self._run("radio", "wifi", "on")
        except RadioError:
            pass

    def start_hotspot(self) -> None:
        self.wifi_on()
        if self._hotspot_is_up():
            return
        try:
            self._run("connection", "up", self.hotspot_connection, timeout=20)
            return
        except RadioError:
            pass
        self._run(
            "device",
            "wifi",
            "hotspot",
            "ifname",
            self.device,
            "ssid",
            self.hotspot_ssid,
            "password",
            self.hotspot_password,
            "con-name",
            self.hotspot_connection,
            timeout=30,
        )

    def stop_hotspot(self) -> None:
        for args in (
            ("connection", "down", self.hotspot_connection),
            ("connection", "delete", self.hotspot_connection),
        ):
            try:
                self._run(*args, timeout=15)
            except RadioError:
                pass

    def join(self, ssid: str, password: str) -> None:
        self.wifi_on()
        self.stop_hotspot()
        args = ["device", "wifi", "connect", ssid, "ifname", self.device]
        if password:
            args.extend(["password", password])
        self._run(*args, timeout=45)

    def _hotspot_is_up(self) -> bool:
        return active_connection(self.device_fields()) == self.hotspot_connection


def _nmcli(*args: str, timeout: float = 30) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            ["nmcli", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RadioError("nmcli is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise RadioError("nmcli timed out") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "nmcli failed").strip()
        raise RadioError(err)
    return completed.stdout
