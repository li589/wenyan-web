from __future__ import annotations

import json
import os as _os
import subprocess as _sp
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from style_prompt import build_prompt
import apikey

ROOT = Path(__file__).parent
PORT = 8765
MAX_BODY_BYTES = 1 * 1024 * 1024   # 请求体上限 1MB，防止被大请求阻塞
REQUEST_TIMEOUT = 90                # 秒


# ---------------------------------------------------------------------------
# 协议适配器：每种协议三件事不同 — 端点路径 / 请求体 / 认证头。
# 通过 ADAPTERS 字典统一收口，新增协议只要加一条目。
# ---------------------------------------------------------------------------

def build_openai(command: str, model: str) -> tuple[str, dict, dict]:
    """OpenAI 兼容协议。覆盖 DeepSeek / Moonshot / 智谱 / SiliconFlow / OpenRouter 等。"""
    return (
        "chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": build_prompt(command)}],
            "temperature": 0.8,
            "stream": False,
        },
        {"Content-Type": "application/json"},
    )


def build_gemini(command: str, model: str) -> tuple[str, dict, dict]:
    """Google Gemini 原生协议。"""
    return (
        f"v1beta/models/{model}:generateContent",
        {
            "contents": [
                {"role": "user", "parts": [{"text": build_prompt(command)}]},
            ],
            "generationConfig": {"temperature": 0.8},
        },
        {"Content-Type": "application/json"},
    )


def build_anthropic(command: str, model: str) -> tuple[str, dict, dict]:
    """Anthropic Claude 原生协议。"""
    return (
        "v1/messages",
        {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": build_prompt(command)}],
        },
        {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
    )


def parse_openai(result: dict) -> dict:
    msg = result.get("choices", [{}])[0].get("message", {})
    return {
        "reasoning_content": msg.get("reasoning_content", "") or "",
        "output": msg.get("content", "") or "",
    }


def parse_gemini(result: dict) -> dict:
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    thinking_parts = []
    text_parts = []
    for p in parts:
        # Gemini 的 thought 通常是布尔标记，真正的内容仍在 text 字段里。
        text = p.get("text", "")
        if p.get("thought") is True:
            if text:
                thinking_parts.append(text)
            continue
        thinking = p.get("thinking")
        if isinstance(thinking, str) and thinking:
            thinking_parts.append(thinking)
            continue
        if isinstance(text, str) and text:
            text_parts.append(text)
    return {
        "reasoning_content": "\n".join(thinking_parts).strip(),
        "output": "".join(text_parts).strip(),
    }


def parse_anthropic(result: dict) -> dict:
    blocks = result.get("content", [])
    thinking_parts = [b.get("thinking", "") for b in blocks if b.get("type") == "thinking"]
    text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return {
        "reasoning_content": "\n".join(thinking_parts).strip(),
        "output": "\n".join(text_parts).strip(),
    }


ADAPTERS: dict[str, dict[str, Any]] = {
    "openai":    {"build": build_openai,    "parse": parse_openai,    "auth_header": "Authorization",  "auth_prefix": "Bearer "},
    "gemini":    {"build": build_gemini,    "parse": parse_gemini,    "auth_header": "x-goog-api-key", "auth_prefix": ""},
    "anthropic": {"build": build_anthropic, "parse": parse_anthropic, "auth_header": "x-api-key",      "auth_prefix": ""},
}


def call_llm(
    command: str,
    api_key: str | None = None,
    api_base: str | None = None,
    api_type: str | None = None,
    model: str | None = None,
) -> dict:
    key = api_key or apikey.API_KEY
    base = (api_base or apikey.API_BASE).rstrip("/")
    kind = apikey.detect_type(api_type, api_base)
    selected_model = (model or apikey.MODEL).strip()
    if not key:
        return {"error": "API Key 不能为空"}
    if not base:
        return {"error": "API Base 不能为空"}
    if not selected_model:
        return {"error": "Model 不能为空"}
    if kind not in ADAPTERS:
        return {"error": f"未知的 API 类型: {kind}"}
    adapter = ADAPTERS[kind]

    path, body, extra_headers = adapter["build"](command, selected_model)

    # Gemini 走 query string ?key=xxx；其它两家走请求头
    if kind == "gemini":
        url = f"{base}/{path}?key={urllib.parse.quote(key)}"
    else:
        url = f"{base}/{path}"

    headers = dict(extra_headers)
    if adapter["auth_prefix"]:
        headers[adapter["auth_header"]] = f"{adapter['auth_prefix']}{key}"
    else:
        headers[adapter["auth_header"]] = key

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {exc.code}: {detail}"}
    except urllib.error.URLError as exc:
        return {"error": f"连接失败: {exc.reason}"}
    except TimeoutError:
        return {"error": "请求超时"}

    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        return {"error": f"响应不是合法 JSON: {raw_bytes[:200]!r}"}

    parsed = adapter["parse"](raw)
    if not parsed.get("output"):
        parsed["_raw"] = raw
    return parsed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.address_string()}] {format % args}")

    def _send_json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, path: Path, status: int = 200) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            return self._send_json(404, {"error": "资源不存在"})
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> tuple[dict | None, str | None]:
        """统一读取 JSON 请求体，带上限和格式校验。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "Content-Length 格式错误"
        if length <= 0:
            return None, "缺少请求体"
        if length > MAX_BODY_BYTES:
            return None, f"请求体过大（上限 {MAX_BODY_BYTES} 字节）"
        try:
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, "请求体格式错误"
        return data, None

    def do_OPTIONS(self) -> None:
        self._send_json(204, {})

    def do_GET(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/api/config":
            return self._send_json(200, apikey.export_public_config())
        if self.path in ("/V1", "/v1"):
            return self._send_html(ROOT / "frontend_v1.html")
        if self.path in ("/", "/V2", "/v2"):
            return self._send_html(ROOT / "frontend_v2.html")
        return self._send_json(404, {"error": "路径不存在"})

    def do_POST(self) -> None:
        if self.path == "/api/generate":
            return self._handle_generate()
        if self.path == "/api/config":
            return self._handle_config()
        return self._send_json(404, {"error": "路径不存在"})

    def _handle_generate(self) -> None:
        data, err = self._read_json_body()
        if err:
            return self._send_json(400, {"error": err})
        assert data is not None

        command = str(data.get("command", "")).strip()
        if not command:
            return self._send_json(400, {"error": "command 不能为空"})

        result = call_llm(
            command=command,
            api_key=data.get("api_key") or None,
            api_base=data.get("api_base") or None,
            api_type=data.get("api_type") or None,
            model=data.get("model") or None,
        )

        if "error" in result:
            return self._send_json(502, result)

        self._send_json(
            200,
            {
                "prompt": build_prompt(command),
                "reasoning_content": result.get("reasoning_content", ""),
                "output": result.get("output", ""),
            },
        )

    def _handle_config(self) -> None:
        data, err = self._read_json_body()
        if err:
            return self._send_json(400, {"error": err})
        assert data is not None

        cfg = {}
        for k in ("API_TYPE", "API_BASE", "API_KEY", "MODEL"):
            val = data.get(k.lower())
            if val and isinstance(val, str):
                cfg[k] = val.strip()

        if cfg:
            apikey.save_config(cfg)
            apikey.apply_runtime_config(cfg)
        self._send_json(200, {"saved": list(cfg.keys())})


def _kill_port(port: int) -> None:
    """Windows 下清理占用端口的进程，仅在开发启动时使用。"""
    try:
        out = _sp.check_output(["netstat", "-ano"], text=True, stderr=_sp.DEVNULL)
    except (_sp.CalledProcessError, FileNotFoundError, OSError):
        return

    current_pid = _os.getpid()
    pids = {
        l.split()[-1]
        for l in out.splitlines()
        if f":{port}" in l and "LISTENING" in l
    }
    for pid in pids:
        try:
            if int(pid) == current_pid:
                continue
        except ValueError:
            continue
        _sp.run(["taskkill", "/PID", pid, "/F"], capture_output=True)


def main() -> None:
    _kill_port(PORT)
    print(f"http://127.0.0.1:{PORT}/V2     卡片面板")
    print(f"http://127.0.0.1:{PORT}/V1     极简风格")
    print(f"当前 API 类型: {apikey.detect_type(apikey.API_TYPE, apikey.API_BASE)}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
