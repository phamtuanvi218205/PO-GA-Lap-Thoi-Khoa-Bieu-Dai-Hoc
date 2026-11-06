"""Launcher checks with no browser, live server, SQL or optimizer calls."""

import importlib.util
from pathlib import Path
import threading
from unittest.mock import Mock, patch

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "Script" / "start_demo.py"
SPEC = importlib.util.spec_from_file_location("demo_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_check_only_never_starts_app():
    with patch.object(launcher, "check_environment"), \
         patch.object(launcher, "run_server") as server, \
         patch.object(launcher, "is_our_server") as probe:
        assert launcher.main(["--check"]) == 0
        server.assert_not_called()
        probe.assert_not_called()


def test_missing_dependency_is_reported():
    with patch.object(launcher.importlib.util, "find_spec", return_value=None):
        with pytest.raises(RuntimeError, match="fastapi"):
            launcher.check_environment()


def test_old_python_is_rejected():
    with patch.object(launcher.sys, "version_info", (3, 10)):
        with pytest.raises(RuntimeError, match="3.11"):
            launcher.check_environment()


@pytest.fixture
def safe_main():
    with patch.object(launcher, "check_environment"), \
         patch.object(launcher.os, "chdir"), \
         patch.object(launcher.sys, "path", launcher.sys.path.copy()):
        yield


def test_existing_app_is_reused(safe_main):
    with patch.object(launcher, "is_our_server", return_value=True), \
         patch.object(launcher, "open_browser") as browser, \
         patch.object(launcher, "run_server") as server:
        assert launcher.main([]) == 0
        browser.assert_called_once()
        server.assert_not_called()


def test_occupied_port_does_not_stop_other_app(safe_main):
    with patch.object(launcher, "is_our_server", return_value=False), \
         patch.object(launcher, "port_available", return_value=False), \
         patch.object(launcher, "run_server") as server:
        with pytest.raises(RuntimeError, match="ung dung khac"):
            launcher.main([])
        server.assert_not_called()


def test_launch_calls_existing_entry_point(safe_main):
    with patch.object(launcher, "is_our_server", return_value=False), \
         patch.object(launcher, "port_available", return_value=True), \
         patch.object(launcher.threading, "Thread") as thread, \
         patch.object(launcher, "run_server", return_value=0) as server:
        assert launcher.main([]) == 0
        server.assert_called_once_with()
        thread.return_value.start.assert_called_once()
        assert thread.call_args.kwargs["args"][0].is_set()


def test_browser_waits_for_ready_server():
    with patch.object(launcher, "is_our_server", side_effect=[False, True]) as probe, \
         patch.object(launcher, "open_browser") as browser:
        stop = Mock()
        stop.is_set.return_value = False
        launcher.wait_then_open(stop, timeout=10)
        assert probe.call_count == 2
        stop.wait.assert_called_once()
        browser.assert_called_once()


def test_stopped_server_does_not_open_browser():
    stop = threading.Event()
    stop.set()
    with patch.object(launcher, "open_browser") as browser:
        launcher.wait_then_open(stop)
        browser.assert_not_called()


def test_unrelated_http_server_is_not_reused():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    with patch.object(launcher, "build_opener", return_value=opener), \
         patch.object(launcher.json, "load", side_effect=[
             {"status": "ok"}, {"info": {"title": "Other app"}}
         ]):
        assert not launcher.is_our_server()


def test_connection_failure_is_not_readiness():
    with patch.object(launcher, "build_opener", side_effect=OSError("offline")):
        assert not launcher.is_our_server()
