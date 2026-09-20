"""Minimal streaming chat client with per-turn and cumulative token usage."""

from __future__ import annotations

from typing import Any

from services.model_provider import get_selected_model_connection


def get_field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from either an SDK object or a dictionary."""
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def usage_values(usage: Any) -> dict[str, int]:
    """Extract standard and provider-specific cached token counters."""
    prompt_details = get_field(usage, "prompt_tokens_details")
    completion_details = get_field(usage, "completion_tokens_details")

    cached_input = first_number(
        get_field(usage, "cached_tokens"),
        get_field(usage, "cache_read_input_tokens"),
        get_field(usage, "prompt_cache_hit_tokens"),
        get_field(prompt_details, "cached_tokens"),
        get_field(prompt_details, "cache_read_input_tokens"),
        get_field(prompt_details, "prompt_cache_hit_tokens"),
    )

    return {
        "input": get_field(usage, "prompt_tokens", 0) or 0,
        "output": get_field(usage, "completion_tokens", 0) or 0,
        "total": get_field(usage, "total_tokens", 0) or 0,
        "cached_input": cached_input,
        "reasoning": get_field(completion_details, "reasoning_tokens", 0) or 0,
    }


def first_number(*values: Any) -> int:
    for value in values:
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def add_usage(total: dict[str, int], current: dict[str, int]) -> None:
    for key in total:
        total[key] += current[key]


def print_usage(label: str, usage: dict[str, int]) -> None:
    print(
        f"[{label}] input={usage['input']} "
        f"output={usage['output']} total={usage['total']} "
        f"cached_input={usage['cached_input']} "
        f"reasoning={usage['reasoning']}"
    )


def main() -> None:
    connection = get_selected_model_connection()
    messages: list[dict[str, str]] = []
    cumulative = {
        "input": 0,
        "output": 0,
        "total": 0,
        "cached_input": 0,
        "reasoning": 0,
    }

    print(f"Model: {connection.model_name}")
    print("输入 exit 或 quit 退出。")

    while True:
        try:
            user_input = input("\n[user]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        current_usage = None
        current_usage_raw = None
        print("[assistant]: ", end="", flush=True)

        try:
            response = connection.client.chat.completions.create(
                model=connection.model_name,
                messages=messages,
                stream=True,
                # Ask the compatible endpoint to send usage in the final frame.
                stream_options={"include_usage": True},
            )

            full_content = ""
            for chunk in response:
                usage = get_field(chunk, "usage")
                if usage is not None:
                    current_usage = usage_values(usage)
                    current_usage_raw = usage

                choices = get_field(chunk, "choices", []) or []
                if not choices:
                    continue
                delta = get_field(choices[0], "delta")
                content = get_field(delta, "content")
                if content:
                    print(content, end="", flush=True)
                    full_content += content

            print()
            messages.append({"role": "assistant", "content": full_content})

            if current_usage is None:
                print("[usage] 服务端没有返回 usage 数据")
            else:
                add_usage(cumulative, current_usage)
                print_usage("usage", current_usage)
                print_usage("cumulative", cumulative)
                print(f"[usage_raw] {current_usage_raw}")
        except Exception as exc:
            # Remove the failed user turn so a transient error does not corrupt history.
            messages.pop()
            print(f"\n[error] {exc}")


if __name__ == "__main__":
    main()
