
import logging
import os

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response

app = FastAPI()
logger = logging.getLogger(__name__)

KAKAO_CALLBACK_URL = "https://kapi.kakao.com/v1/bot/callback"


@app.get("/")
async def home():
    return {"status": "ok", "service": "aitop100-agent"}


@app.get("/health")
async def health():
    return {"status": "ok"}


def extract_message_text(data: dict) -> str:
    """Return the user message without logging the full Kakao event."""
    content = data.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "plainText", "message"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def send_kakao_reply(callback_token: str, text: str) -> None:
    bot_token = os.getenv("KAKAO_BOT_TOKEN")
    if not bot_token:
        logger.error("KAKAO_BOT_TOKEN is not configured")
        return

    headers = {
        "Authorization": f"KakaoAK {bot_token}",
        "X-Bot-Callback-Token": callback_token,
        "Content-Type": "application/json",
    }
    body = {
        "skillResponse": {
            "version": "2.0",
            "template": {
                "outputs": [{"simpleText": {"text": text[:1000]}}],
            },
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                KAKAO_CALLBACK_URL,
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(
                "Kakao callback completed: total=%s sent=%s failed=%s",
                result.get("totalCount"),
                result.get("sendCount"),
                result.get("errorCount"),
            )
    except (httpx.HTTPError, ValueError):
        logger.exception("Kakao callback request failed")


@app.post("/webhook/kakao", status_code=204)
async def kakao_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    event = await request.json()

    event_type = event.get("t", "unknown")
    logger.info("Kakao event received: type=%s", event_type)

    if event.get("op") == "DISPATCH" and event_type == "MESSAGE_CREATE":
        data = event.get("d") or {}
        callback_token = data.get("callbackToken")
        message_text = extract_message_text(data)

        if callback_token and message_text:
            background_tasks.add_task(
                send_kakao_reply,
                callback_token,
                message_text,
            )
        else:
            logger.warning(
                "MESSAGE_CREATE ignored: callback_token=%s message_text=%s",
                bool(callback_token),
                bool(message_text),
            )

    # Kakao bot webhooks require a 2xx response within one second.
    return Response(status_code=204)
