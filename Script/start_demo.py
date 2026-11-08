"""Double-click launcher support; does not install packages or change SQL config."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Core Algrithms" / "src"
HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}"
DEPENDENCIES = ("fastapi", "uvicorn", "numpy", "openpyxl", "pyodbc", "multipart", "dotenv")


def check_environment() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Can Python 3.11 tro len.")
    if not (SOURCE / "gapo_timetabling" / "__main__.py").is_file():
        raise RuntimeError("Khong thay source. Giu file CMD va thu muc Script trong du an.")
    missing = [name for name in DEPENDENCIES if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Thieu thu vien: " + ", ".join(missing))


def is_our_server() -> bool:
    """Probe read-only routes; never use a database route to test startup."""
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(URL + "/health", timeout=1) as response:
            if json.load(response) != {"status": "ok"}:
                return False
        with opener.open(URL + "/openapi.json", timeout=1) as response:
            schema = json.load(response)
        return schema.get("info", {}).get("title") == "GA-PO Timetabling API"
    except (OSError, URLError, ValueError, AttributeError, TypeError):
        return False


def port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((HOST, PORT))
        except OSError:
            return False
    return True


def open_browser() -> None:
    try:
        if not webbrowser.open(URL):
            print(f"Khong tu mo duoc trinh duyet. Mo thu cong: {URL}", flush=True)
    except webbrowser.Error:
        print(f"Mo trinh duyet tai: {URL}", flush=True)


def wait_then_open(stop: threading.Event, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not stop.is_set() and time.monotonic() < deadline:
        if is_our_server():
            if not stop.is_set():
                open_browser()
            return
        stop.wait(0.5)
    if not stop.is_set():
        print(f"Server chua san sang. Xem loi trong cua so nay; dia chi: {URL}", flush=True)


def run_server() -> int:
    # Same entry point and defaults as the existing manual launch command.
    from gapo_timetabling.application.app_cli import main as application_main

    return application_main(["serve-api", "--host", HOST, "--port", str(PORT)])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check_environment()
    if args == ["--check"]:
        print("Moi truong Python san sang.")
        return 0
    if args:
        raise RuntimeError("Tham so khong hop le.")
    os.chdir(ROOT)
    sys.path.insert(0, str(SOURCE))
    if is_our_server():
        print(f"Ung dung da chay. Dang mo {URL}", flush=True)
        open_browser()
        return 0
    if not port_available():
        raise RuntimeError(
            f"Cong {PORT} dang do ung dung khac su dung. "
            "Khong tu dung tien trinh khac; hay giai phong cong roi thu lai."
        )
    print(f"Dang mo ung dung: {URL}\n"
          "Giu cua so nay trong khi su dung. Nhan Ctrl+C de dung server.\n"
          "Doc ket noi tu .env; can SQL Server san sang.\n"
          "Database/bang can duoc tao truoc bang Script/KHOI_TAO_DATABASE.sql.\n"
          "Server giu nguyen co che khoi phuc job dang cho cua du an.", flush=True)
    stop = threading.Event()
    browser = threading.Thread(target=wait_then_open, args=(stop,), daemon=True)
    browser.start()
    try:
        return run_server()
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
        browser.join(timeout=3)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Khong khoi dong duoc ung dung: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
