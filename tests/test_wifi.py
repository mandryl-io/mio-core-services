import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mio_core_services.wifi.fade import FADE_PERIOD, fade_level
from mio_core_services.wifi.nmcli import (
    HOTSPOT_CONNECTION,
    Network,
    Radio,
    RadioError,
    has_ipv4,
    is_home_connected,
    parse_connect_body,
    parse_device_show,
    parse_wifi_list,
    split_nmcli,
)
from mio_core_services.wifi.server import SetupState, serve


def test_split_nmcli_unescapes_colons_in_ssid():
    assert split_nmcli(r"Home\:Net:80:WPA2") == ["Home:Net", "80", "WPA2"]


def test_parse_wifi_list_keeps_strongest_and_drops_hidden():
    text = "\n".join(
        [
            "Home:40:WPA2",
            "Home:88:WPA2",
            ":10:WPA2",
            "Cafe:55:WPA1 WPA2",
            "Open:20:",
        ]
    )
    networks = parse_wifi_list(text)
    assert [net.ssid for net in networks] == ["Home", "Cafe", "Open"]
    assert networks[0].signal == 88
    assert networks[2].security == ""


def test_is_home_connected_needs_client_lease_and_some_connectivity():
    fields = parse_device_show(
        "GENERAL.CONNECTION:HomeWifi\nIP4.ADDRESS[1]:192.168.1.20/24\n"
    )
    assert is_home_connected(fields, "full")
    assert is_home_connected(fields, "limited")
    assert not is_home_connected(fields, "none")


def test_setup_hotspot_is_not_home_wifi():
    fields = parse_device_show(
        f"GENERAL.CONNECTION:{HOTSPOT_CONNECTION}\nIP4.ADDRESS[1]:10.42.0.1/24\n"
    )
    assert not is_home_connected(fields, "none")
    assert not is_home_connected(fields, "full")


def test_missing_ipv4_or_connection_is_not_connected():
    assert not has_ipv4({"GENERAL.CONNECTION": "Home"})
    assert not is_home_connected({"GENERAL.CONNECTION": "--"}, "full")
    assert not is_home_connected(
        {"GENERAL.CONNECTION": "Home", "IP4.ADDRESS[1]": ""}, "full"
    )


def test_parse_connect_body_requires_a_network_name():
    ssid, password = parse_connect_body({"ssid": " Home ", "password": "secret"})
    assert (ssid, password) == ("Home", "secret")
    with pytest.raises(ValueError):
        parse_connect_body({"ssid": "  "})
    with pytest.raises(ValueError):
        parse_connect_body({"ssid": 1})
    assert parse_connect_body({"ssid": "Open"}) == ("Open", "")


def test_fade_starts_on_then_goes_dark_then_on():
    assert fade_level(0.0) == pytest.approx(1.0)
    assert fade_level(FADE_PERIOD / 2) == pytest.approx(0.0)
    assert fade_level(FADE_PERIOD) == pytest.approx(1.0)
    assert fade_level(FADE_PERIOD / 4) == pytest.approx(0.5)
    for step in range(21):
        value = fade_level(FADE_PERIOD * step / 20)
        assert 0.0 - 1e-9 <= value <= 1.0 + 1e-9


def test_radio_reports_home_connection_from_nmcli_text():
    def run(*args, timeout=30):
        if args == ("networking", "connectivity"):
            return "full\n"
        if args == ("-t", "device", "show", "wlan0"):
            return "GENERAL.CONNECTION:Kitchen\nIP4.ADDRESS[1]:10.0.0.8/24\n"
        raise AssertionError(args)

    assert Radio(run=run).is_home_connected()


class FakeRadio:
    hotspot_ssid = "Mio-Setup"

    def __init__(self) -> None:
        self.networks = [Network("Kitchen", 70, "WPA2"), Network("Cafe", 40, "")]
        self.joined: tuple[str, str] | None = None
        self.home = False
        self.hotspot_up = True
        self.fail_join_with: str | None = None

    def scan(self):
        return self.networks

    def join(self, ssid: str, password: str) -> None:
        if self.fail_join_with:
            raise RadioError(self.fail_join_with)
        self.joined = (ssid, password)
        self.home = True
        self.hotspot_up = False

    def is_home_connected(self) -> bool:
        return self.home

    def start_hotspot(self) -> None:
        self.hotspot_up = True

    def active_ssid(self):
        if self.joined:
            return self.joined[0]
        return self.hotspot_ssid


def _json(url: str, data=None, method=None):
    body = None if data is None else json.dumps(data).encode()
    request = Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read().decode())


def test_http_lists_networks_and_serves_the_app(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Mio</h1>", encoding="utf-8")
    radio = FakeRadio()
    server = serve(SetupState(radio), host="127.0.0.1", port=0, app_dir=tmp_path)
    try:
        port = server.server_address[1]
        status, payload = _json(f"http://127.0.0.1:{port}/api/networks")
        assert status == 200
        assert payload["networks"][0]["ssid"] == "Kitchen"
        mode, body = _json(f"http://127.0.0.1:{port}/api/status")
        assert mode == 200
        assert body["mode"] == "setup"
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert b"Mio" in response.read()
    finally:
        server.shutdown()


def test_http_connect_joins_and_marks_done():
    radio = FakeRadio()
    state = SetupState(radio)
    server = serve(state, host="127.0.0.1", port=0, app_dir="app")
    try:
        port = server.server_address[1]
        status, payload = _json(
            f"http://127.0.0.1:{port}/api/connect",
            data={"ssid": "Kitchen", "password": "secret"},
        )
        assert status == 200
        assert payload["ok"] is True
        assert state.done.wait(timeout=2)
        assert radio.joined == ("Kitchen", "secret")
        _, body = _json(f"http://127.0.0.1:{port}/api/status")
        assert body["mode"] == "connected"
        assert body["ssid"] == "Kitchen"
    finally:
        server.shutdown()


def test_http_connect_restores_hotspot_on_failure():
    radio = FakeRadio()
    radio.fail_join_with = "secrets were rejected"
    state = SetupState(radio)
    server = serve(state, host="127.0.0.1", port=0, app_dir="app")
    try:
        port = server.server_address[1]
        _json(
            f"http://127.0.0.1:{port}/api/connect",
            data={"ssid": "Kitchen", "password": "nope"},
        )
        deadline = threading.Event()
        for _ in range(20):
            _, body = _json(f"http://127.0.0.1:{port}/api/status")
            if body["mode"] == "setup" and body.get("error"):
                assert "rejected" in body["error"]
                assert radio.hotspot_up
                deadline.set()
                break
            deadline.wait(0.05)
        assert deadline.is_set()
        assert not state.done.is_set()
    finally:
        server.shutdown()


def test_http_rejects_empty_ssid():
    server = serve(SetupState(FakeRadio()), host="127.0.0.1", port=0, app_dir="app")
    try:
        port = server.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/connect",
            data=b'{"ssid":"  "}',
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=2)
        assert caught.value.code == 400
    finally:
        server.shutdown()


def test_run_in_thread_runs_the_passed_function():
    from mio_core_services.wifi.bootstrap import run_in_thread

    done = threading.Event()
    thread = run_in_thread(done.set, name="wifi-test")
    assert done.wait(timeout=1)
    thread.join(timeout=1)
