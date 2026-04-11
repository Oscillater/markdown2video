"""Adapter 实现 — 进程内 / CLI / HTTP 三种执行方式。"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict
from urllib.request import Request, urlopen

from md2video.tools.adapter import ExecutionMode


class InProcessAdapter:
    """直接方法调用。"""

    @property
    def execution_mode(self) -> str:
        return ExecutionMode.IN_PROCESS

    def invoke(self, tool: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return tool.execute(input_data)


class CliAdapter:
    """CLI 子进程调用。输入通过 stdin 传 JSON，输出从 stdout 读 JSON。"""

    def __init__(self, command: list[str], timeout: int = 300):
        self.command = command
        self.timeout = timeout

    @property
    def execution_mode(self) -> str:
        return ExecutionMode.CLI

    def invoke(self, tool: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        result = subprocess.run(
            self.command,
            input=json.dumps(input_data, ensure_ascii=False),
            capture_output=True, text=True, timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI tool failed: {result.stderr}")
        return json.loads(result.stdout)


class HttpAdapter:
    """HTTP API 调用。POST JSON 输入，解析 JSON 响应。"""

    def __init__(self, url: str, headers: Dict[str, str] | None = None, timeout: int = 60):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    @property
    def execution_mode(self) -> str:
        return ExecutionMode.HTTP

    def invoke(self, tool: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        req = Request(
            self.url,
            data=json.dumps(input_data, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        with urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())
