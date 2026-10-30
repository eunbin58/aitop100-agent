
from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/")
async def home():
    return {"status": "ok", "service": "aitop100-agent"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/kakao")
async def kakao_webhook(request: Request):
    event = await request.json()

    # 개발 중에만 이벤트 종류를 확인
    # 토큰과 사용자 정보가 포함될 수 있으므로
    # 원본 이벤트 전체를 로그에 남기지 않음
    print("Kakao event:", event.get("t", "unknown"))

    return {"status": "received"}
