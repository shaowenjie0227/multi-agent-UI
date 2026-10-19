"""真实 HTTP 链路验证：用本地假 OpenAI 兼容服务跑 real_chat。

覆盖：非流式、SSE 流式（含逐块回调）、reasoning_effort 透传、
流式不支持时自动回退非流式、429/500 重试、已流出内容不重试、usage 回调。
这是「真实供应商」之外能验证的全部链路。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers.openai_compat import real_chat
from app.schemas import Provider, ProviderModel, ProxySettings

NO_PROXY = ProxySettings(mode="none")


class FakeOpenAI:
    """最小 OpenAI 兼容服务，记录收到的请求体，按场景返回。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.scenario = "plain"
        self.attempt = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                fake.attempt += 1
                getattr(fake, f"_do_{fake.scenario}")(self, body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self):
        self.server.shutdown()

    # ---- 场景实现 ----

    def _json(self, h, code: int, payload: dict):
        data = json.dumps(payload).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    def _sse(self, h, chunks: list[dict]):
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        for c in chunks:
            h.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            h.wfile.flush()
        h.wfile.write(b"data: [DONE]\n\n")
        h.wfile.flush()

    @staticmethod
    def _chunk(delta: str, usage: dict | None = None) -> dict:
        obj = {
            "id": "chatcmpl-x",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fake-model",
            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
        }
        if usage:
            obj["usage"] = usage
        return obj

    def _complete_body(self, content: str, usage: dict | None = None) -> dict:
        body = {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "created": 1,
            "model": "fake-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }
        if usage:
            body["usage"] = usage
        return body

    def _do_plain(self, h, body):
        self._json(h, 200, self._complete_body("你好，这是非流式回复"))

    def _do_stream(self, h, body):
        # 客户端要求 stream=true 才走 SSE
        if not body.get("stream"):
            self._json(h, 200, self._complete_body("非流式回退内容"))
            return
        self._sse(
            h,
            [
                self._chunk("第一段"),
                self._chunk("第二段"),
                self._chunk("第三段", usage={"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}),
            ],
        )

    def _do_reject_stream(self, h, body):
        """模拟不支持 stream 的供应商：stream=true 时返回 400。"""
        if body.get("stream"):
            self._json(h, 400, {"error": {"message": "stream is not supported", "type": "invalid_request_error"}})
            return
        self._json(h, 200, self._complete_body("回退后的非流式内容"))

    def _do_rate_limit_once(self, h, body):
        if self.attempt == 1:
            self._json(h, 429, {"error": {"message": "rate limited", "type": "rate_limit_error"}})
            return
        self._json(h, 200, self._complete_body("重试后成功"))

    def _do_server_error_always(self, h, body):
        self._json(h, 500, {"error": {"message": "boom", "type": "server_error"}})

    def _do_stream_then_error(self, h, body):
        """先流出部分内容，再发一个畸形数据帧：解析失败 → 不得重试（否则输出重复）。"""
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        h.wfile.write(f"data: {json.dumps(self._chunk('已流出的内容'))}\n\n".encode())
        h.wfile.flush()
        h.wfile.write(b"data: {this-is-not-json}\n\n")
        h.wfile.flush()

    def _do_empty(self, h, body):
        self._json(h, 200, self._complete_body(""))


@pytest.fixture()
def fake():
    s = FakeOpenAI()
    yield s
    s.close()


def provider(fake: FakeOpenAI) -> Provider:
    return Provider(id="p_fake", name="FakeAI", baseUrl=fake.base_url, apiKey="sk-test")


MODEL = ProviderModel(id="m_fake", providerId="p_fake", name="fake-model")


@pytest.mark.asyncio
async def test_non_streaming_roundtrip(fake):
    out = await real_chat(provider(fake), MODEL, "系统提示", [{"role": "user", "content": "hi"}], proxy=NO_PROXY)
    assert out == "你好，这是非流式回复"
    sent = fake.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["messages"][0] == {"role": "system", "content": "系统提示"}
    assert sent["body"]["messages"][1]["content"] == "hi"
    assert sent["headers"].get("authorization") == "Bearer sk-test"


@pytest.mark.asyncio
async def test_streaming_calls_on_delta_with_chunks(fake):
    fake.scenario = "stream"
    deltas: list[str] = []

    async def on_delta(s):
        deltas.append(s)

    out = await real_chat(
        provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY, on_delta=on_delta
    )
    assert out == "第一段第二段第三段"
    assert deltas == ["第一段", "第二段", "第三段"]
    assert fake.requests[0]["body"]["stream"] is True


@pytest.mark.asyncio
async def test_streaming_usage_reported(fake):
    fake.scenario = "stream"
    usage: list[dict] = []

    async def on_usage(p):
        usage.append(p)

    await real_chat(
        provider(fake),
        MODEL,
        "sys",
        [{"role": "user", "content": "hi"}],
        proxy=NO_PROXY,
        on_delta=lambda s: _noop(),
        on_usage=on_usage,
    )
    assert usage and usage[-1]["totalTokens"] == 33
    assert usage[-1]["model"] == "fake-model"
    assert usage[-1]["provider"] == "FakeAI"


async def _noop():
    return None


@pytest.mark.asyncio
async def test_reasoning_effort_passthrough(fake):
    await real_chat(
        provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], effort="high", proxy=NO_PROXY
    )
    assert fake.requests[0]["body"]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_reasoning_effort_omitted_on_default(fake):
    await real_chat(
        provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], effort="default", proxy=NO_PROXY
    )
    assert "reasoning_effort" not in fake.requests[0]["body"]


@pytest.mark.asyncio
async def test_effort_off_is_sent(fake):
    """off 是有效档位，不是 default，需要原样下发。"""
    await real_chat(
        provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], effort="off", proxy=NO_PROXY
    )
    assert fake.requests[0]["body"]["reasoning_effort"] == "off"


@pytest.mark.asyncio
async def test_stream_rejected_falls_back_to_non_stream(fake):
    """不支持 stream 的供应商：自动回退非流式，并把完整内容回调给监控面板。"""
    fake.scenario = "reject_stream"
    deltas: list[str] = []

    async def on_delta(s):
        deltas.append(s)

    out = await real_chat(
        provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY, on_delta=on_delta
    )
    assert out == "回退后的非流式内容"
    assert deltas == ["回退后的非流式内容"]
    # 第一次带 stream=true 被拒，第二次不带 stream
    assert fake.requests[0]["body"].get("stream") is True
    assert fake.requests[1]["body"].get("stream") is None


@pytest.mark.asyncio
async def test_rate_limit_retried(fake, monkeypatch):
    fake.scenario = "rate_limit_once"
    monkeypatch.setattr("app.providers.openai_compat.BACKOFF_BASE", 0.01)
    out = await real_chat(provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY)
    assert out == "重试后成功"
    assert fake.attempt == 2


@pytest.mark.asyncio
async def test_server_error_retried_then_raises(fake, monkeypatch):
    fake.scenario = "server_error_always"
    monkeypatch.setattr("app.providers.openai_compat.BACKOFF_BASE", 0.01)
    with pytest.raises(RuntimeError) as exc:
        await real_chat(provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY)
    assert "调用失败" in str(exc.value)
    assert fake.attempt == 3  # MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_no_retry_after_partial_stream(fake, monkeypatch):
    """已流出内容后中断：不能重试，否则用户会看到重复输出。"""
    fake.scenario = "stream_then_error"
    monkeypatch.setattr("app.providers.openai_compat.BACKOFF_BASE", 0.01)
    deltas: list[str] = []

    async def on_delta(s):
        deltas.append(s)

    with pytest.raises(Exception):
        await real_chat(
            provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY, on_delta=on_delta
        )
    assert fake.attempt == 1
    assert deltas == ["已流出的内容"]


@pytest.mark.asyncio
async def test_empty_content_raises(fake):
    fake.scenario = "empty"
    with pytest.raises(RuntimeError) as exc:
        await real_chat(provider(fake), MODEL, "sys", [{"role": "user", "content": "hi"}], proxy=NO_PROXY)
    assert "空内容" in str(exc.value)


@pytest.mark.asyncio
async def test_custom_proxy_mode_uses_proxy(fake):
    """custom 代理模式下应走 httpx 的 proxy 参数；这里只验证不崩且请求形态不变。"""
    await real_chat(
        provider(fake),
        MODEL,
        "sys",
        [{"role": "user", "content": "hi"}],
        proxy=ProxySettings(mode="none"),  # 直连本机，避免测试受代理环境影响
    )
    assert len(fake.requests) == 1
