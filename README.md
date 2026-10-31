# AI TOP 100 교동몰 상담 에이전트

카카오톡 고객 메시지를 받아 수집한 정책·인터뷰·원본 문서에서 관련 근거를 검색하고, 필요한 경우 액션 API를 조회하거나 요청을 접수한 뒤 SimpleText로 답변하는 FastAPI 앱입니다.

## 주요 기능

- 85개 지식 조각에서 문의별 관련 근거 검색, 개정본·신규 인터뷰·공개 TC 규칙 우선
- 최근 대화 8개와 미완성 요청의 필수값을 기본 1시간 동안 인메모리 유지
- 주문·배송·결제·정기배송·상품·재고·조합원·쿠폰·적립금·프로모션 조회
- 환불, 배송지·배송일·주문품목 변경, 주문 메모, 재배송, 긴급 출고, 현금영수증, 쿠폰, 재입고 알림, 카드 취소, 정기배송 변경, 담당자 이관 접수
- 상태 변경 전 필수값과 기본 상태 검증
- 접수와 실제 처리 완료를 구분
- 카카오 SimpleText 한 말풍선, 최대 500자

## 환경변수

Render에는 최소 다음 값을 설정합니다.

- `KAKAO_BOT_TOKEN`
- `ACTION_API_TOKEN`
- `OPENAI_API_KEY`

선택값은 `.env.example`을 참고합니다. 비밀값은 코드나 Git에 저장하지 않습니다.

## 실행

```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

- 상태 확인: `GET /health`
- 카카오 웹훅: `POST /webhook/kakao`

## 지식 자료

- `knowledge/knowledge_index.json`: 런타임 검색 인덱스
- `knowledge/notion_knowledge_hub.md`: 인터뷰·정책 정리본
- `knowledge/notion_operation_notes.md`: 운영 기록
- `knowledge/actions.json`: 액션 API 명세
- `knowledge/interview_test_cases.md`: 추가 인터뷰·공개 사례에서 일반화한 규칙
- `knowledge/raw/`, `knowledge/extracted/`: 로컬 원본 보관용이며 Git에서는 제외

원본 자료가 바뀌면 다음 명령으로 인덱스를 다시 만듭니다.

```powershell
python build_knowledge.py
```

## 안전 원칙

- 조회·접수에는 대화에서 받은 동일한 TC ID를 사용합니다.
- 환불·변경 API 성공은 업무 완료가 아니라 요청 접수입니다.
- 정책이나 필수값이 불명확하면 실행하지 않고 필요한 정보만 요청합니다.
- 미완성 요청은 대화에서 추가 정보를 받아 채우며, 고객이 취소하거나 주제를 바꾸면 이전 요청을 실행하지 않습니다.
- 생산자 개인정보와 매입·정산·수수료 등 내부 정보는 검색되어도 공개하지 않습니다.
