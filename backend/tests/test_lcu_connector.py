from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings, _default_lockfile_path
from app.services.draft_state_builder import DraftStateBuilder
from app.services.lcu_connector import LcuConnector


def build_connector() -> LcuConnector:
    return LcuConnector(Settings(), DraftStateBuilder())


def test_is_wsl_detects_microsoft_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = build_connector()

    monkeypatch.setattr("app.services.lcu_connector.sys.platform", "linux")
    monkeypatch.setattr("app.services.lcu_connector.platform.uname", lambda: SimpleNamespace(release="6.1.21-microsoft-standard-WSL2"))

    assert connector._is_wsl() is True


def test_parse_process_output_extracts_lcu_credentials() -> None:
    connector = build_connector()

    output = (
        "\"C:\\Riot Games\\League of Legends\\LeagueClientUx.exe\" "
        "\"--install-directory=C:\\Riot Games\\League of Legends\" "
        "\"--app-port=51234\" "
        "\"--remoting-auth-token=super-secret\""
    )

    assert connector._parse_process_output(output) == {
        "process_name": "LeagueClientUx",
        "pid": "0",
        "port": "51234",
        "password": "super-secret",
        "protocol": "https",
        "install_directory": "C:\\Riot Games\\League of Legends",
    }


def test_parse_process_output_returns_none_for_empty_output() -> None:
    connector = build_connector()

    assert connector._parse_process_output("") is None
    assert connector._parse_process_output("   ") is None


def test_default_lockfile_path_uses_existing_windows_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.sys.platform", "win32")
    monkeypatch.setattr(
        "app.config.Path.exists",
        lambda self: str(self) == r"D:\Riot Games\League of Legends\lockfile",
    )

    assert str(_default_lockfile_path()) == r"D:\Riot Games\League of Legends\lockfile"
