from __future__ import annotations

# API_TYPE 可选：openai / gemini / anthropic
#   openai     —— OpenAI 兼容协议（DeepSeek / Moonshot / 智谱 / SiliconFlow / OpenRouter / 通义千问 OpenAI 模式 等绝大多数厂商）
#   gemini     —— Google Gemini 原生协议（generativelanguage.googleapis.com）
#   anthropic  —— Anthropic Claude 原生协议（api.anthropic.com）
#
# 注意：如果你在界面上手动选择了协议类型，以界面为准。否则将根据 API_BASE 自动推断。
API_TYPE = 'openai'

API_BASE = 'https://api.deepseek.com'
API_KEY = ''
MODEL = 'deepseek-chat'

CONFIG_KEYS = ("API_TYPE", "API_BASE", "API_KEY", "MODEL")


def save_config(data: dict[str, str]) -> None:
    """把界面上的配置写回到本文件中。仅修改有传值的字段。"""
    from pathlib import Path

    path = Path(__file__)
    source = path.read_text("utf-8")
    lines = source.splitlines(keepends=True)

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for key in CONFIG_KEYS:
            if key in data and stripped.startswith(f"{key} ="):
                lines[i] = f"{key} = {data[key]!r}\n"
                break

    path.write_text("".join(lines), "utf-8")


def apply_runtime_config(data: dict[str, str]) -> None:
    """同步更新当前进程中的配置，避免必须重启服务才能生效。"""
    for key in CONFIG_KEYS:
        if key in data:
            globals()[key] = data[key]


def export_public_config() -> dict[str, str | bool]:
    """导出可返回给前端的配置，不直接暴露 API Key。"""
    return {
        "api_type": API_TYPE,
        "api_base": API_BASE,
        "model": MODEL,
        "has_api_key": bool(API_KEY),
    }


def detect_type(api_type: str | None, api_base: str | None) -> str:
    """根据用户选择或 URL 推断协议类型。"""
    if api_type:
        t = api_type.strip().lower()
        if t in ("openai", "gemini", "anthropic"):
            return t

    base = (api_base or API_BASE).lower()
    if "anthropic.com" in base:
        return "anthropic"
    if "generativelanguage.googleapis.com" in base or "googleapis.com" in base:
        return "gemini"
    return "openai"
