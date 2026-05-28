from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


WEBHOOK_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    "?key=5b37e38b-6a50-40e9-b7bf-ab6ed563bce0"
)
DEFAULT_PICURL = "https://t.tutu.to/img/PqB5h"


class NewsRequest(BaseModel):
    """发送企微图文消息的请求参数。"""

    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    picurl: str | None = None


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


@app.get("/")
def hello_world() -> dict[str, str]:
    """返回 Hello World，用于验证 API 服务是否正常启动。"""
    return {"message": "Hello World!"}


@app.post("/send-news")
async def send_news(request: NewsRequest) -> dict[str, Any]:
    """发送企微群聊机器人图文消息。"""
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
        response = await client.post(WEBHOOK_URL, json=payload)
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"调用企微接口失败：{exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="企微接口返回的不是合法 JSON") from exc

    if result.get("errcode") != 0:
        raise HTTPException(status_code=502, detail=result)

    return result


if __name__ == "__main__":
    import uvicorn

    # 允许 Python 小白直接运行 main.py 启动服务。
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
