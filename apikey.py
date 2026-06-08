from __future__ import annotations

API_BASE = "https://api.deepseek.com"
API_KEY = ""
MODEL = "deepseek-v4-flash"


def save_config(data: dict[str, str]) -> None:
    from pathlib import Path

    path = Path(__file__)
    source = path.read_text("utf-8")
    lines = source.splitlines(keepends=True)

    for i, line in enumerate(lines):
        for key in ("API_BASE", "API_KEY", "MODEL"):
            if key in data and line.startswith(f"{key} ="):
                lines[i] = f"{key} = {data[key]!r}\n"
                break

    path.write_text("".join(lines), "utf-8")
