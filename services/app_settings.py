"""Persistent application-wide settings."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import config


DEFAULT_TOOL_ROUND_LIMIT = 100
DEFAULT_SHOW_USAGE = True
MIN_TOOL_ROUND_LIMIT = 1
MAX_TOOL_ROUND_LIMIT = 100
MODEL_PROVIDERS = {"siliconflow", "custom"}


def get_app_settings() -> dict[str, int | bool | str]:
    state = _read_state()
    show_usage = state.get("show_usage", DEFAULT_SHOW_USAGE)
    if not isinstance(show_usage, bool):
        raise ValueError("用量显示开关必须是布尔值")
    model_provider = state.get("model_provider", "siliconflow")
    if model_provider not in MODEL_PROVIDERS:
        raise ValueError("未知的模型配置")
    return {
        "tool_round_limit": _validate_tool_round_limit(state["tool_round_limit"]),
        "show_usage": show_usage,
        "model_provider": model_provider,
    }


def save_app_settings(
    tool_round_limit: int,
    show_usage: bool,
    model_provider: str,
) -> dict[str, int | bool | str]:
    value = _validate_tool_round_limit(tool_round_limit)
    if not isinstance(show_usage, bool):
        raise ValueError("用量显示开关必须是布尔值")
    if model_provider not in MODEL_PROVIDERS:
        raise ValueError("未知的模型配置")
    _write_state({
        "tool_round_limit": value,
        "show_usage": show_usage,
        "model_provider": model_provider,
    })
    return get_app_settings()


def _read_state() -> dict[str, Any]:
    path = config.APP_SETTINGS_FILE
    if not path.exists():
        return {"tool_round_limit": DEFAULT_TOOL_ROUND_LIMIT}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"设置文件损坏：{exc}") from exc
    if not isinstance(state, dict) or "tool_round_limit" not in state:
        raise ValueError("设置文件格式错误")
    return state


def _validate_tool_round_limit(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not MIN_TOOL_ROUND_LIMIT <= value <= MAX_TOOL_ROUND_LIMIT
    ):
        raise ValueError(
            f"工具调用轮数上限必须是 {MIN_TOOL_ROUND_LIMIT}-{MAX_TOOL_ROUND_LIMIT} 之间的整数"
        )
    return value


def _write_state(state: dict[str, Any]) -> None:
    path = config.APP_SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(state, temporary_file, ensure_ascii=False, indent=2)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
