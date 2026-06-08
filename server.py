from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import subprocess as _sp
import sys as _sys

from style_prompt import build_prompt
import apikey

ROOT = Path(__file__).parent
PORT = 8765


def make_payload(command: str) -> dict:
    return {
        "model": apikey.MODEL,
        "messages": [{"role": "user", "content": build_prompt(command)}],
        "temperature": 0.8,
        "stream": False,
        "thinking": {"type": "enabled"},
    }


def call_llm(payload: dict, api_key: str | None = None, api_base: str | None = None) -> dict:
    key = api_key or apikey.API_KEY
    base = (api_base or apikey.API_BASE).rstrip("/")
    url = f"{base}/chat/completions"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"}
    except urllib.error.URLError as exc:
        return {"error": f"连接失败: {exc.reason}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.address_string()}] {format % args}")

    def _send_json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, path: Path, status: int = 200) -> None:
        raw = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/v1":
            return self._send_html(ROOT / "frontend_v1.html")
        if self.path in ("/", "/v2"):
            return self._send_html(ROOT / "frontend_v2.html")
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/generate":
            return self._handle_generate()
        if self.path == "/api/config":
            return self._handle_config()
        self.send_error(404)

    def _handle_generate(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, ValueError):
            return self._send_json(400, {"error": "请求体格式错误"})

        command = str(data.get("command", "")).strip()
        if not command:
            return self._send_json(400, {"error": "命令不能为空"})

        payload = make_payload(command)
        result = call_llm(
            payload,
            api_key=data.get("api_key") or None,
            api_base=data.get("api_base") or None,
        )

        if "error" in result:
            self._send_json(500, result)
            return

        msg = result.get("choices", [{}])[0].get("message", {})
        self._send_json(
            200,
            {
                "prompt": build_prompt(command),
                "reasoning_content": msg.get("reasoning_content", ""),
                "output": msg.get("content", ""),
            },
        )

    def _handle_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, ValueError):
            return self._send_json(400, {"error": "请求体格式错误"})

        cfg = {}
        for k in ("API_BASE", "API_KEY", "MODEL"):
            if data.get(k.lower()):
                cfg[k] = data[k.lower()]

        if cfg:
            apikey.save_config(cfg)
        self._send_json(200, {"saved": list(cfg.keys())})


def _kill_port(port: int) -> None:
    out = _sp.check_output(["netstat", "-ano"], text=True)
    pids = {l.split()[-1] for l in out.splitlines() if f":{port}" in l and "LISTENING" in l}
    for pid in pids:
        if pid != str(_sys.gettrace() or -1):
            _sp.run(["taskkill", "//PID", pid, "//F"], capture_output=True)


def main() -> None:
    _kill_port(PORT)
    print(f"http://127.0.0.1:{PORT}        卡片面板")
    print(f"http://127.0.0.1:{PORT}/v1     极简风格")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
