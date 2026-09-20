"""Model provider credentials and per-task OpenAI-compatible clients."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

import config


SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_MODEL_NAME = "deepseek-ai/DeepSeek-V4-Flash"


@dataclass(frozen=True)
class ModelConnection:
    client: Any
    model_name: str


def get_model_settings(model_provider: str) -> dict[str, Any]:
    state = _read_credentials()
    custom = state["custom"]
    return {
        "model_provider": model_provider,
        "siliconflow": {
            "base_url": SILICONFLOW_BASE_URL,
            "model_name": SILICONFLOW_MODEL_NAME,
            "has_api_key": bool(state["siliconflow"]["api_key"]),
        },
        "custom": {
            "base_url": custom["base_url"],
            "model_name": custom["model_name"],
            "has_api_key": bool(custom["api_key"]),
        },
    }


def save_model_settings(
    model_provider: str,
    siliconflow_api_key: str | None,
    custom_base_url: str,
    custom_model_name: str,
    custom_api_key: str | None,
) -> dict[str, Any]:
    state = _read_credentials()
    if siliconflow_api_key is not None:
        state["siliconflow"]["api_key"] = siliconflow_api_key.strip()
    if custom_api_key is not None:
        state["custom"]["api_key"] = custom_api_key.strip()
    state["custom"]["base_url"] = _normalize_base_url(custom_base_url)
    state["custom"]["model_name"] = custom_model_name.strip()
    _selected_config(model_provider, state)
    _write_credentials(state)
    return get_model_settings(model_provider)


def get_model_connection(model_provider: str) -> ModelConnection:
    selected = _selected_config(model_provider, _read_credentials())
    return ModelConnection(
        client=OpenAI(api_key=selected["api_key"], base_url=selected["base_url"]),
        model_name=selected["model_name"],
    )


def get_selected_model_connection() -> ModelConnection:
    from services.app_settings import get_app_settings

    settings = get_app_settings()
    return get_model_connection(str(settings["model_provider"]))


def _default_credentials() -> dict[str, dict[str, str]]:
    return {
        "siliconflow": {"api_key": ""},
        "custom": {"base_url": "", "model_name": "", "api_key": ""},
    }


def _read_credentials() -> dict[str, dict[str, str]]:
    path = config.MODEL_CREDENTIALS_FILE
    if not path.exists():
        return _default_credentials()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"模型凭据文件损坏：{exc}") from exc
    if not isinstance(state, dict):
        raise ValueError("模型凭据文件格式错误")
    siliconflow = state.get("siliconflow")
    custom = state.get("custom")
    if (
        not isinstance(siliconflow, dict)
        or not isinstance(siliconflow.get("api_key"), str)
        or not isinstance(custom, dict)
        or any(not isinstance(custom.get(field), str) for field in ("base_url", "model_name", "api_key"))
    ):
        raise ValueError("模型凭据文件格式错误")
    return state


def _selected_config(
    model_provider: str,
    state: dict[str, dict[str, str]],
) -> dict[str, str]:
    if model_provider == "siliconflow":
        config_data = {
            "base_url": SILICONFLOW_BASE_URL,
            "model_name": SILICONFLOW_MODEL_NAME,
            "api_key": state["siliconflow"]["api_key"].strip(),
        }
    elif model_provider == "custom":
        custom = state["custom"]
        config_data = {
            "base_url": _normalize_base_url(custom["base_url"]),
            "model_name": custom["model_name"].strip(),
            "api_key": custom["api_key"].strip(),
        }
    else:
        raise ValueError("未知的模型配置")

    if not config_data["api_key"]:
        raise ValueError("尚未配置 API Key")
    if not config_data["base_url"]:
        raise ValueError("Base URL 不能为空")
    if not config_data["model_name"]:
        raise ValueError("Model Name 不能为空")
    return config_data


def _normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    return base_url


def _write_credentials(state: dict[str, Any]) -> None:
    path = config.MODEL_CREDENTIALS_FILE
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
