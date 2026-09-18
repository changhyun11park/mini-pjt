# 미니 PJT :[주말 여행지 추천 Agent]

임직원 이름과 지역명만 입력하면, 가족 구성에 맞는 주말 여행지·교통비·소요시간·주변 명소·주변 맛집을 한 번에 요약해 주는 사내 인사팀용 Agent다. 자세한 서비스 스펙은[SERVICE.md](SERVICE.md) 참고.

## 사용자

- 임직원 복지 프로그램을 운영하는 **인사팀 담당자**.

## 사용 목적

인사팀이 매주 대상 임직원에게 복지성 주말 여행을 추천하려면, 그때그때 여행지·교통비·소요시간·주변 명소·주변 맛집을 일일이 검색해야 했다. 지금까지는 이걸 수기로 검색하거나,
가족 구성과 무관한 획일적인 안내문을 보내는 식으로 해결해 왔다.

## 좋아지는 점

- 대상 임직원과 지역(정확한 목적지든 "강원도"처럼 넓은 지역이든)만 입력하면 맞춤 여행지·교통비 추정치·소요시간·근처 가볼 만한 곳·주변 맛집이 한 번에 요약되어 나온다.
- 획일적인 안내문과 달리, 가족 구성(미성년 자녀 동반/커플/1인 가구/그 외 가족여행)에 따라 추천 명소와 추천 사유의 어투가 달라진다.
- 동명이인·미등록 임직원·지역, 북한·해외처럼 다녀올 수 없는 지역은 지어내지 않고 즉시 안내하거나 되묻는다.
- 인사팀 담당자가 준비하는 시간을 줄이고, 임직원이 체감하는 복지 수준을 높인다.

## 사용 방법

1. 의존성 설치, `.env`에 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION`
   (Bedrock), `KAKAO_REST_API_KEY`(카카오 디벨로퍼스), `EX_CO_KR_API_KEY`(공공데이터포털 한국도로공사)를 채운다.
2. 서버 실행:
   ```bash
   cd src
   uvicorn api:app
   ```
3. 브라우저로 `http://localhost:8000` 접속 — 임직원 이름·지역명을 입력하고 "추천받기"를 누르면 답변이 나온다. 입력창 하단 "조회 결과" 표에는 지금까지 조회가 완료된 임직원·지역명이 쌓이고, 이름을 클릭하면 해당 답변으로 스크롤 이동한다.
   - 동명이인이면 후보 목록이 버튼으로 나오니 대상자를 선택한다.
   - API로 직접 붙이려면 `POST /query`에 `{"question": "{이름}님 {지역} 여행 추천해줘"}`를
     보내면 `answer`/`contexts`/`trace` 세 키로 응답이 온다.
4. 평가·회귀 테스트: `evaluation/` 아래 있음.
   ```bash
   python evaluation/run_eval.py           # 실제 API·LLM을 호출해 16개 케이스 실행,
                                            # evaluation/results/round_NN/에 결과+리포트 저장
   pytest evaluation/test_core_logic.py -v # 최근 라운드 결과를 규칙(공식·마스킹·형식)으로 재검증
   ```

## Agent 아키텍처

```
mini-pjt_{박창현}/                   # 주말 여행지 추천 Agent
├── src/                            # 소스코드
│   ├── api.py                      # FastAPI 앱 - POST /query, GET /(웹 클라이언트)
│   ├── fast_path.py                # 질문에서 이름·지역 추출 후 가드레일 즉답/파이프라인/에이전트로 분기
│   ├── pipeline.py                 # 도구 호출을 고정 순서로 실행 + LLM 1회 호출로 답변 조립
│   ├── agent.py                    # 이름·지역을 못 뽑는 자유 문장을 처리하는 ReAct 폴백 에이전트
│   ├── mcp_server.py               # 도구 5개를 MCP 서버로 노출(agent.py가 구독)
│   ├── tool_employee.py            # Search_Employee - 이름/사번으로 가족 구성 조회, 동명이인 판정
│   ├── tool_place.py               # Recommend_place - 지역+가족구성으로 명소 추천(가족 적합도·언급빈도 50:50)
│   ├── tool_price_time.py          # Price_Time - 통행료·거리·편도 소요시간 조회
│   ├── tool_restaurant.py          # Nearby_Restaurant - 실제 소요시간(30분, 없으면 60분) 기준 주변 맛집 조회
│   ├── tool_traffic_calculator.py  # Traffic_Calculator - 왕복 교통비 계산
│   ├── kakao_client.py             # 카카오 API 공용 헬퍼(인증 헤더, 블로그 언급 수, 실제 소요시간 조회)
│   ├── region_validator.py         # 지역 입력값 검증(북한·해외·존재하지 않는 지역 판정)
│   ├── link_section.py             # 답변 후처리 - 소제목·굵은 라벨 자리에만 링크 삽입 + 방어 코드
│   ├── masking.py                  # 출력 가드레일 - 가족 구성원 이름·나이 마스킹
│   ├── context_trace.py            # ReAct 에이전트 메시지에서 contexts/trace 추출
│   ├── resilient_llm.py            # ThrottlingException 시 다른 Bedrock 모델로 자동 전환
│   └── static/
│       └── index.html              # 웹 클라이언트(입력 폼 + 조회 결과 표 + 답변 렌더링)
├── data/
│   ├── employee.json               # 임직원 더미 데이터(이름·사번·가족 구성)
│   └── Ex_Office_Coor.json         # 전국 고속도로 영업소 좌표 더미 데이터
├── evaluation/
│   ├── test_queries.csv            # 평가용 16개 질문 세트
│   ├── rules.py                    # 규칙 기반 자동 채점 로직(공식·마스킹·형식 검증)
│   ├── rounds.py                   # 라운드(round_NN) 폴더 생성·조회
│   ├── run_eval.py                 # 실제 API·LLM으로 16개 케이스를 실행해 새 라운드를 만듦
│   ├── report.py                   # 라운드 결과를 사람이 읽는 report.md로 정리
│   ├── test_core_logic.py          # 가장 최근 라운드를 규칙으로 재검증하는 pytest
│   └── results/round_NN/           # 라운드별 실행 결과(case_XX.json) + report.md
├── SERVICE.md                      # 서비스 스펙(사용자·도구·가드레일·성공 기준)
├── CLAUDE.md                       # 프로젝트 규칙(기술 스택·폴더 구조·코드 규칙)
├── README.md                       # 이 파일
└── .gitignore
```

## API 스펙 (표준 규약)

### `GET /`

정적 웹 클라이언트(`src/static/index.html`)를 그대로 서빙한다. 내부적으로 `POST /query`만 호출한다.

### `POST /query`

**Request**

```json
{ "question": "박도윤님 전주시 완산구 여행 추천해줘" }
```

- `question` (string, 필수): `"{이름 또는 사번}님 {지역} 여행 추천해줘"` 형식이면 `fast_path.py`가 이름·지역을 뽑아 즉시 처리한다.
  형식에 안 맞는 자유 문장이면 전체 ReAct 에이전트(`agent.py`)가 대신 처리한다.

**Response** — 세 경우 모두 항상 같은 3개 키로 응답한다.

```json
{
  "answer": "string  — 마크다운 답변, 또는 가드레일 안내문",
  "contexts": [ { "tool": "string", "result": {"...": "도구 원본 결과"} } ],
  "trace":    [ { "seq": 0, "type": "tool_call | tool_result | answer", "name": "string" } ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `answer` | string | 최종 답변(마크다운) 또는 가드레일 고정 안내문. |
| `contexts` | `{tool, result}[]` | 이번 요청에서 실제로 호출된 도구(`search_employee`/`recommend_place`/`price_time`/`nearby_restaurant`/`traffic_calculator`)의 원본 결과를 호출 순서대로 담는다 — 채점·디버깅 시 "지어낸 값인지" 대조하는 기준이 된다. |
| `trace` | 배열 | 도구 호출(`tool_call`)·결과(`tool_result`)·최종 답변(`answer`) 이벤트를 `seq` 순서로 나열한 실행 로그. |

**실제 응답 예시 — 가드레일(미등록 임직원)**: `{"question": "홍길동님 제주도 여행 추천해줘"}`

```json
{
  "answer": "'홍길동' 임직원을 찾을 수 없습니다.",
  "contexts": [
    { "tool": "search_employee", "result": { "error": "'홍길동' 임직원을 찾을 수 없습니다." } }
  ],
  "trace": [
    { "seq": 1, "type": "tool_call", "name": "search_employee", "args": { "name_or_id": "홍길동" } },
    { "seq": 2, "type": "tool_result", "name": "search_employee", "content": "{\"error\": ...}" }
  ]
}
```

**응답이 갈리는 3가지 경로** (`fast_path.py`가 판정)

| 경로 | 조건 | `contexts`에 담기는 도구 |
|---|---|---|
| 가드레일 즉답 | 동명이인 / 미등록 임직원·지역 / 북한 / 해외 | `search_employee`(+ 지역 문제면 `recommend_place`)만 |
| 정상 추천 완료 | 임직원 1명 + 유효한 지역 확정 | 5개 도구 전부(`search_employee`→`recommend_place`→`price_time`·`nearby_restaurant`→`traffic_calculator`) |
| 자유 문장 | 질문에서 이름·지역을 못 뽑음 | 전체 ReAct 에이전트가 필요에 따라 호출한 도구들 |

## 회고: 평가 라운드별 개선 시도

> **1차(round_01) 6/16(37.5%) → 9차(round_09) 16/16(100%).** 가장 크게 기여한 변경은 round_04의 `linkify_places` 수정이다 — 명소 이름에 링크를 거는 위치를 "텍스트 처음 등장하는 자리"에서 "소제목·굵은 라벨 자리"로 정확히 고치면서 통과율이 11/16에서 16/16으로 뛰었다.

`evaluation/run_eval.py`로 16개 평가 케이스를 실행할 때마다 라운드가 하나씩 쌓인다
(`evaluation/results/round_NN/report.md`). 지금까지 **총 9회** 실행했고, 그 중 5번은 문제를 찾거나 로직을 개선해 코드를 고친 뒤 재실행한 경우다.

| 라운드 | 통과 | 발견한 문제 / 개선 내용 |
|---|---|---|
| round_01 | 6/16 | 참고 자료 표 뒤에 "🔗 참고 링크" 섹션이 덧붙어 "표가 답변의 마지막"이라는 규칙을 어김. |
| round_02 | 11/16 | 코드는 그대로였지만(라운드별 기록 방식만 정비한 뒤 재확인) 같은 근본 버그가 이번엔 다른 형태로 나타남 — 명소 링크가 소제목이 아니라 인사말·본문 중간에 잘못 걸림. LLM 응답이 매번 달라 같은 버그도 증상이 매번 다르게 보였다. |
| round_03 | 11/16 | 다시 살펴보니 FAIL 5건 전부 새 버그가 아니라 **평가 스크립트(rules.py)**가 최신 답변 형식(함께 갈 곳 후보 1곳→소제목, 2곳→굵은 글씨)을 못 따라가서 생긴 오탐이었다. 이 조사 중 진짜 원인을 확정: `linkify_places`가 이름이 "텍스트 전체에서 처음 등장하는 자리"에 링크를 거는 방식이라, 소제목보다 인사말에 이름이 먼저 나오면 소제목에는 링크가 안 걸림. |
| round_04 | **16/16** | `linkify_places`를 정규식 기반으로 고쳐 소제목·굵은 라벨 자리에만 정확히 링크를 걸도록 수정. LLM이 스스로 링크를 쓰거나 표 뒤에 내용을 덧붙이는 경우를 막는 방어 코드(`strip_markdown_links`, `truncate_after_table`)도 추가. 평가 스크립트도 최신 답변 형식에 맞게 동기화. |
| round_05 | 16/16 | 명소 추천 기준을 "언급 빈도만" → "가족 구성 적합도 50% + 블로그 언급 빈도 50%"로 변경(가족이 없는 임직원에게도 항상 아이 동반형 명소만 추천되는 문제 보완). 회귀 없음 확인. |
| round_06 | 16/16 | 50:50 가중치로도 안 걸러지는 경우(언급 건수가 압도적으로 많은 동물원 등)를 위해, 이름에 "키즈"·"동물원"·"체험"이 들어간 후보를 자녀 없는 1인 가구·커플 대상에서 미리 제외하는 필터 추가. 회귀 없음 확인. |
| round_07 | 16/16 | 추가 코드 변경 없이 재실행 — 안정성 재확인. |
| round_08 | 16/16 | `Nearby_Restaurant`(주변 맛집)의 기준을 "반경 1.5km"에서 "실제 편도 소요시간 30분 이내(카카오모빌리티 길찾기로 실측), 하나도 없으면 60분 이내로 확장"으로 변경 — `recommend_place`의 '그 외 가볼만한 곳'과 같은 방식으로 통일. 길찾기 로직(`real_duration_min`)은 `tool_place.py`에서 `kakao_client.py`로 옮겨 공용화. 회귀 없음 확인. |
| round_09 | 16/16 | "신동현님 경기도 과천"처럼 키워드가 붙은 검색어("과천 가족여행")가 카카오에서 1건만 나와 '함께 가볼 곳'이 비어버리는 문제 발견. 후보가 3건 미만이면 지역명 단독 검색("과천")으로 보충하도록 `recommend_place`를 수정. 회귀 없음 확인. |
