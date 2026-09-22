"""pytest 引导：把仓库根目录加入模块搜索路径，并提供真实 HTTP 服务夹具。

HTTP 冒烟不使用测试客户端库，而是以子进程方式启动与生产一致的
uvicorn 服务（`python -m uvicorn app.main:app`），再用标准库
urllib 发请求，从而真正覆盖 ASGI/HTTP 栈。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def server_base() -> str:
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": ROOT, "PORT": str(port)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("uvicorn 子进程提前退出")
            try:
                with urllib.request.urlopen(base + "/health", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.2)
        else:
            proc.terminate()
            raise RuntimeError("等待 /health 就绪超时")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session")
def http_call(server_base):
    """返回 request(method, path, json_body=None, raw=None) -> (status, body)。"""

    def request(method: str, path: str, json_body=None, raw: bytes | None = None):
        if raw is not None:
            data = raw
            headers = {"Content-Type": "application/json"}
        elif json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        else:
            data = None
            headers = {}
        req = urllib.request.Request(
            server_base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read().decode("utf-8")
                return resp.status, json.loads(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(payload)
            except json.JSONDecodeError:
                return exc.code, payload

    return request
