import logging
import os

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("kakao-bot")

app = FastAPI()

KAKAO_CALLBACK_URL = "https://kapi.kakao.com/v1/bot/callback"
OP_DISPATCH = 0  # 문서 기준: op는 정수 0


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # 어떤 경로/메서드든 서버에 도착하면 기록 (본문·토큰은 기록하지 않음)
    logger.info("REQ %s %s", request.method, request.url.path)
    return await call_next(request)


@app.get("/")
async def home():
    return {"status": "ok", "service": "aitop100-agent"}


@app.get("/health")
async def health():
    return {"status": "ok"}


def extract_message_text(data: dict) -> str:
    # 문서 기준 메시지는 d.content(문자열). 다른 형태도 방어적으로 처리
    for key in ("content", "text", "message", "plainText", "utterance"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for sub in ("text", "plainText", "message", "content"):
                sv = value.get(sub)
                if isinstance(sv, str) and sv.strip():
                    return sv.strip()
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
            "template": {"outputs": [{"simpleText": {"text": text[:1000]}}]},
        }
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                KAKAO_CALLBACK_URL, headers=headers, json=body
            )
        if response.status_code != 200:
            logger.error(
                "Kakao callback failed: status=%s body=%s",
                response.status_code,
                response.text[:300],
            )
            return
        result = response.json()
        logger.info(
            "Kakao callback completed: total=%s sent=%s failed=%s",
            result.get("totalCount"),
            result.get("sendCount"),
            result.get("errorCount"),
        )
    except Exception:
        logger.exception("Kakao callback request failed")


@app.post("/webhook/kakao", status_code=204)
async def kakao_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    try:
        event = await request.json()
    except Exception:
        logger.warning("Webhook body is not valid JSON")
        return Response(status_code=204)
    if not isinstance(event, dict):
        return Response(status_code=204)

    data = event.get("d") if isinstance(event.get("d"), dict) else {}
    op = event.get("op")
    event_type = event.get("t", "unknown")
    # 구조 파악용: 값은 남기지 않고 키 이름만 기록
    logger.info("EVENT op=%r t=%s d_keys=%s", op, event_type, sorted(data))

    if op in (OP_DISPATCH, "DISPATCH") and event_type == "MESSAGE_CREATE":
        callback_token = data.get("callbackToken")
        message_text = extract_message_text(data)
        if callback_token:
            background_tasks.add_task(
                send_kakao_reply,
                callback_token,
                f"echo: {message_text}",
            )
        else:
            logger.warning("MESSAGE_CREATE without callbackToken")

    # 카카오 웹훅은 1초 이내 2xx 응답 필요 (본문 없음)
    return Response(status_code=204)