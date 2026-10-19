"""为所有部署提供同源查看器代理、跨源隔离响应头及双向 WebSocket 转发。"""

import asyncio
from contextlib import suppress
import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response, StreamingResponse
import httpx
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from .config import VIEWER_URL
from .sessions import SessionManager

ISOLATION_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "X-Content-Type-Options": "nosniff",
}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}
logger = logging.getLogger(__name__)


class IsolationHeaders:
    """使用纯 ASGI 中间件，同时覆盖静态页面、代理响应和 WebSocket 握手。"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        async def send_with_headers(message: Message):
            if message["type"] in {"http.response.start", "websocket.accept"}:
                headers = MutableHeaders(scope=message)
                headers.update(ISOLATION_HEADERS)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ViewerGateway:
    def __init__(self, manager: SessionManager):
        self.manager = manager
        # 回环请求不使用宿主机的 HTTP_PROXY，也不允许请求参数指定代理目标。
        # 上游由 websockets 的 HTTP 握手钩子服务普通请求，发送后即关闭 TCP。
        # 禁用闲置连接复用，避免下一请求与上游关闭连接竞争；客户端对象仍复用。
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30, connect=3),
                                        limits=httpx.Limits(max_keepalive_connections=0))

    async def close(self):
        await self.client.aclose()

    async def http(self, request: Request, path: str = ""):
        port = self.manager.active_port()
        if port is None:
            raise HTTPException(503, "当前没有运行中的查看器会话")
        # 路径只追加到固定回环源；查询字符串原样保留，支持上游模型分块下载。
        url = httpx.URL(f"http://127.0.0.1:{port}/").copy_with(
            path="/" + path, query=request.scope.get("query_string", b""))
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in HOP_HEADERS | {"host", "cookie", "authorization", "content-length"}}
        headers["connection"] = "close"
        try:
            upstream = await self.client.send(
                self.client.build_request("GET", url, headers=headers), stream=True)
        except httpx.RequestError as error:
            logger.warning("查看器 HTTP 代理失败 (%s): %s", type(error).__name__, error)
            raise HTTPException(502, "查看器暂时不可达，请检查会话状态") from error
        excluded = HOP_HEADERS | {
            name.strip().lower() for name in upstream.headers.get("connection", "").split(",")}
        response_headers = {key: value for key, value in upstream.headers.items()
                            if key.lower() not in excluded}
        # 上游握手 HTTP 仅支持 GET；HEAD 复用同一资源的响应头，不向调用方发送内容。
        if request.method == "HEAD":
            await upstream.aclose()
            return Response(status_code=upstream.status_code, headers=response_headers)

        async def body():
            try:
                # 保留原始编码和长度，避免 WASM 大文件在代理内重复解压或整体缓存。
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(body(), status_code=upstream.status_code, headers=response_headers)

    async def websocket(self, websocket: WebSocket):
        port = self.manager.active_port()
        if port is None:
            await websocket.close(code=1013, reason="当前没有运行中的查看器会话")
            return
        target = f"ws://127.0.0.1:{port}{websocket.url.path}"
        if websocket.url.query:
            target += "?" + websocket.url.query
        accepted = False
        try:
            async with connect(target, proxy=None, max_size=None, compression=None,
                               open_timeout=5, close_timeout=2,
                               subprotocols=websocket.scope.get("subprotocols") or None) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)
                accepted = True

                async def to_viewer():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            # 浏览器异常断开时的保留代码不能作为关闭帧发送。
                            code = message.get("code", 1000)
                            await upstream.close(code=code if code not in {1005, 1006, 1015} else 1001)
                            return
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None
                                            else message["text"])

                async def to_browser():
                    try:
                        async for message in upstream:
                            if isinstance(message, bytes):
                                await websocket.send_bytes(message)
                            else:
                                await websocket.send_text(message)
                    finally:
                        code = upstream.close_code or 1011
                        await websocket.close(code=code if code not in {1005, 1006, 1015} else 1011,
                                              reason=upstream.close_reason or "")

                tasks = [asyncio.create_task(to_viewer()), asyncio.create_task(to_browser())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    # 任意一侧结束后，取消并等待另一方向，避免换课后遗留后台协程。
                    for task in tasks:
                        task.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception) and not isinstance(
                                result, (ConnectionClosed, WebSocketDisconnect, RuntimeError)):
                            raise result
        except (OSError, TimeoutError, WebSocketException):
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1011 if accepted else 1013, reason="查看器连接已结束或暂时不可达")

    def install(self, app: FastAPI):
        # 路由必须先于课程静态页面挂载；保留官方客户端的根路径协议。
        app.add_api_route(VIEWER_URL.rstrip("/"),
                          lambda: RedirectResponse(VIEWER_URL), include_in_schema=False)
        app.add_api_route(VIEWER_URL + "{path:path}", self.http,
                          methods=["GET", "HEAD"], include_in_schema=False)

        async def model(request: Request):
            return await self.http(request, "model")

        async def asset(request: Request, path: str):
            return await self.http(request, "assets/" + path)

        app.add_api_route("/model", model, methods=["GET", "HEAD"], include_in_schema=False)
        app.add_api_route("/assets/{path:path}", asset, methods=["GET", "HEAD"], include_in_schema=False)
        for path in ("/ui", "/state", "/drop"):
            app.add_api_websocket_route(path, self.websocket)
