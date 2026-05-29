from contextlib import asynccontextmanager
import os
import secrets
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


WEBHOOK_URL_ENV = "WEBHOOK_URL"
API_KEY_ENV = "API_KEY"
DEFAULT_PICURL = "https://t.tutu.to/img/PqB5h"


class NewsRequest(BaseModel):
    """发送企微图文消息的请求参数。"""

    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    picurl: str | None = None


def api_response(code: int = 0, msg: str = "ok", data: Any = None) -> dict[str, Any]:
    """统一 API 返回格式，所有接口都返回 code、msg、data。"""
    return {"code": code, "msg": msg, "data": data}


def get_required_env(name: str) -> str:
    """读取必填环境变量，避免把敏感信息写死在代码里。"""
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=500, detail=f"服务未配置环境变量：{name}")
    return value


def verify_api_key(api_key: str | None) -> None:
    """校验调用方密钥，防止公网接口被陌生人直接调用。"""
    expected_api_key = get_required_env(API_KEY_ENV)
    if not api_key or not secrets.compare_digest(api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效",
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """复用 HTTP 客户端连接，提升多次调用企微接口时的性能。"""
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


# 创建 FastAPI 应用实例，其他用户调用的 API 都挂在这个 app 上。
app = FastAPI(title="wx-push API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """统一处理主动抛出的业务异常。"""
    detail = exc.detail
    if isinstance(detail, dict):
        code = int(detail.get("errcode", exc.status_code))
        msg = str(detail.get("errmsg", "请求失败"))
        data = detail
    else:
        code = exc.status_code
        msg = str(detail)
        data = None

    return JSONResponse(
        status_code=exc.status_code,
        content=api_response(code=code, msg=msg, data=data),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """统一处理请求参数校验失败。"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=api_response(
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            msg="请求参数错误",
            data=exc.errors(),
        ),
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """兜底处理未预期异常，避免返回 FastAPI 默认格式。"""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=api_response(
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            msg="服务器内部错误",
            data=None,
        ),
    )


@app.get("/")
def hello_world() -> dict[str, Any]:
    """返回 Hello World，用于验证 API 服务是否正常启动。"""
    return api_response(data={"message": "Hello World!"})


@app.post("/send-news")
async def send_news(
    request: NewsRequest,
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """发送企微群聊机器人图文消息。"""
    verify_api_key(api_key)
    webhook_url = get_required_env(WEBHOOK_URL_ENV)

    picurl = (request.picurl or "").strip() or DEFAULT_PICURL
    payload = {
        "msgtype": "news",
        "news": {
            "articles": [
                {
                    "title": request.title,
                    "description": request.description,
                    "url": request.url,
                    "picurl": picurl,
                }
            ]
        },
    }

    client: httpx.AsyncClient = app.state.http_client

    try:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"调用企微接口失败：{exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="企微接口返回的不是合法 JSON") from exc

    if result.get("errcode") != 0:
        raise HTTPException(status_code=502, detail=result)

    return api_response(data=result)


if __name__ == "__main__":
    import uvicorn

    # 允许 Python 小白直接运行 main.py 启动服务。
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
