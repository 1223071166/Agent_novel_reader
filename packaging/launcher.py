"""Production launcher for the packaged AgentReader application.

The development workflow continues to use ``run.bat``. This entry point is
responsible for the packaged application only: it selects writable per-user
directories, serves the built React application from FastAPI, opens the
browser, and starts Uvicorn.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import multiprocessing
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Sequence


APP_NAME = "AgentReader"
HOST = "127.0.0.1"
PORT = 8000
STARTUP_TIMEOUT_SECONDS = 120
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def _resource_root() -> Path:
    """Return the read-only directory containing bundled application files."""
    if _is_frozen():
        return Path(sys._MEIPASS).resolve()  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


def _local_app_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).resolve() / APP_NAME
    return Path.home().resolve() / f".{APP_NAME.lower()}"


def _default_data_dir() -> Path:
    if _is_frozen():
        return _local_app_root() / "data"
    return _resource_root() / "data"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 AgentReader")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动服务但不自动打开浏览器，主要用于测试",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="覆盖用户数据目录，主要用于测试",
    )
    return parser.parse_args(argv)


def _configure_runtime(data_dir: Path) -> Path:
    """Create writable directories before importing the application modules."""
    app_root = _local_app_root()
    log_dir = app_root / "logs"
    model_dir = app_root / "models"
    database_dir = data_dir / "database"

    for directory in (data_dir, database_dir, log_dir, model_dir):
        directory.mkdir(parents=True, exist_ok=True)

    os.environ["AGENTREADER_DATA_DIR"] = str(data_dir.resolve())
    os.environ.setdefault("HF_HOME", str(model_dir.resolve()))
    hf_endpoint = os.environ.setdefault("HF_ENDPOINT", DEFAULT_HF_ENDPOINT)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    # hf-mirror serves the regular Hub download URLs.  Disable Xet for this
    # endpoint so huggingface_hub does not try the separate Xet service first
    # and then emit a fallback warning.  A caller that supplies another
    # HF_ENDPOINT keeps control of its own Xet configuration.
    if hf_endpoint.rstrip("/") == DEFAULT_HF_ENDPOINT:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    log_file = log_dir / "launcher.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
        force=True,
    )
    logging.info("模型下载源：%s", hf_endpoint)
    return log_file


def _validate_frontend(frontend_dir: Path) -> None:
    index_file = frontend_dir / "index.html"
    assets_dir = frontend_dir / "assets"
    if not index_file.is_file() or not assets_dir.is_dir():
        raise RuntimeError(
            "没有找到完整的前端构建。请先运行：npm --prefix frontend run build"
        )

    index_html = index_file.read_text(encoding="utf-8")
    referenced_assets = re.findall(
        r"(?:src|href)=[\"'](/assets/[^\"']+)[\"']",
        index_html,
    )
    missing_assets = [
        asset
        for asset in referenced_assets
        if not (frontend_dir / asset.lstrip("/")).is_file()
    ]
    if missing_assets:
        missing = ", ".join(missing_assets)
        raise RuntimeError(
            f"前端构建不完整，缺少文件：{missing}。请重新运行前端构建。"
        )


def _attach_frontend(app: object, frontend_dir: Path) -> None:
    """Attach the built single-page application after all API routes."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    if not isinstance(app, FastAPI):
        raise TypeError("backend.main.app 不是 FastAPI 应用")

    assets_dir = frontend_dir / "assets"
    index_file = frontend_dir / "index.html"
    frontend_root = frontend_dir.resolve()

    app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str):
        if requested_path == "api" or requested_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = (frontend_root / requested_path).resolve()
        try:
            candidate.relative_to(frontend_root)
        except ValueError:
            return FileResponse(index_file)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)


def _ensure_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError as exc:
            raise RuntimeError(
                f"无法启动：本机端口 {PORT} 已被其他程序占用。"
                "请关闭正在运行的 AgentReader 或占用该端口的程序后重试。"
            ) from exc


def _open_browser_when_ready(url: str) -> None:
    health_url = f"{url}/api/health"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    logging.error("服务启动超时，未自动打开浏览器：%s", health_url)


def _show_error(message: str, log_file: Path | None) -> None:
    details = message
    if log_file is not None:
        details += f"\n\n错误日志：{log_file}"
    try:
        ctypes.windll.user32.MessageBoxW(0, details, f"{APP_NAME} 启动失败", 0x10)
    except (AttributeError, OSError):
        print(details, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = _parse_args(argv)
    data_dir = (args.data_dir or _default_data_dir()).expanduser().resolve()
    log_file: Path | None = None

    try:
        log_file = _configure_runtime(data_dir)
        logging.info("正在启动 %s", APP_NAME)
        logging.info("资源目录：%s", _resource_root())
        logging.info("数据目录：%s", data_dir)

        frontend_dir = _resource_root() / "frontend" / "dist"
        _validate_frontend(frontend_dir)
        _ensure_port_available()

        project_root = str(_resource_root())
        if not _is_frozen() and project_root not in sys.path:
            sys.path.insert(0, project_root)

        # Import only after the writable directories and HF_HOME are configured.
        from backend.main import app
        import uvicorn

        _attach_frontend(app, frontend_dir)
        url = f"http://{HOST}:{PORT}"
        if not args.no_browser:
            threading.Thread(
                target=_open_browser_when_ready,
                args=(url,),
                daemon=True,
                name="browser-opener",
            ).start()

        logging.info("服务地址：%s", url)
        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            log_config=None,
            access_log=False,
        )
        return 0
    except Exception as exc:
        logging.exception("AgentReader 启动失败")
        _show_error(str(exc), log_file)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
