# 프로젝트 규칙

## 기술 스택
- Python, LangChain, LangGraph
- 모델은 Amazon Bedrock (ChatBedrockConverse)
- Agent 생성은 langchain.agents 의 create_agent 를 쓴다

## 폴더 구조 (제출 규약. 바꾸지 않는다 — 단, src 밑 .py 파일 이름·개수는 자유롭게 바꿔도 됨)
src/agent.py                   메인 에이전트 그래프 — create_agent 조립, MCP 클라이언트 연결,
                                시스템 프롬프트, 마스킹 미들웨어
src/api.py                     FastAPI 앱, GET /(웹 클라이언트) + POST /query
src/fast_path.py                질문에서 이름·지역을 뽑아 동명이인·미등록 임직원·지역
                                가드레일이면 Bedrock 없이 즉시 답하고, 임직원 1명+유효
                                지역이 확정되면 pipeline.py로, 그 외(자유 문장 등)에는
                                전체 Agent로 넘기도록 판정 (POST /query가 맨 먼저 호출)
src/pipeline.py                 결정적 도구 호출 체인 — recommend_place →
                                price_time·nearby_restaurant(병렬) → traffic_calculator
                                순서를 코드로 고정 실행하고, LLM은 마지막 답변 문장을
                                다듬는 데만 1번 호출 (Bedrock 호출 횟수를 크게 줄임)
src/mcp_server.py               도구 5개(Search_Employee, Recommend_place, Price_Time,
                                Nearby_Restaurant, Traffic_Calculator)를 MCP tool로 노출
src/tool_employee.py           Search_Employee 로직 (동명이인 감지)
src/tool_place.py              Recommend_place 로직 (카카오 디벨로퍼스 API)
src/region_validator.py        지역 입력 검증 (북한/해외/존재하지 않는 지역 판정) — tool_place가 호출
src/tool_price_time.py         Price_Time 로직 (한국도로공사 공공데이터포털 API + 최근접 영업소 계산)
src/tool_restaurant.py         Nearby_Restaurant 로직 (카카오 로컬 API 카테고리 검색)
src/tool_traffic_calculator.py Traffic_Calculator 로직 (순수 계산)
src/kakao_client.py             카카오 API 공용 헬퍼 (인증 헤더, 블로그 언급 건수 — 5분
                                캐싱) — tool_place·tool_restaurant 공용
src/resilient_llm.py           ThrottlingException 시 다른 Bedrock 모델로 자동 전환 (day7_practice 패턴 재사용)
src/masking.py                 출력 가드레일: 가족 이름·나이 마스킹
src/link_section.py            recommend_place·nearby_restaurant 결과의 place_url로
                                본문에 등장하는 명소·맛집 이름을 그 자리에서 마크다운
                                링크로 치환 (agent.py·pipeline.py 공용)
src/context_trace.py           messages에서 contexts/trace 추출
src/static/index.html          로컬 웹 클라이언트 (임직원 이름·지역명 입력 폼, 입력값 한국어 전용
                                필터, 답변을 같은 페이지 입력값 아래에 표시) — api.py의 GET /가 서빙
data/                          임직원 정보 JSON, 전국 고속도로 영업소 좌표 JSON (SERVICE.md 3번 참고)
evaluation/                    test_queries.csv 와 평가 리포트

## 주고받는 형식 (제출 규약)
- POST /query 로 받고 question 필드를 읽는다
- 답은 answer, contexts, trace 세 키로 돌려준다

## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring 을 쓴다
- 비밀 값은 .env 에서 읽고 코드에 적지 않는다

## 이번 서비스: 주말 여행지 추천 Agent (자세한 스펙은 SERVICE.md)

- 도구 5개와 의존 순서: Search_Employee(임직원 가족구성 조회, 더미 JSON) → Recommend_place(카카오
  디벨로퍼스 API로 지역+가족구성 기반 명소 추천) → Price_Time·Nearby_Restaurant(둘 다
  Recommend_place의 추천 명소 좌표를 입력으로 받아 각각 통행료·거리·소요시간, 주변 맛집을
  조회 — 서로 독립적이라 순서 상관없음) → Traffic_Calculator(Price_Time 결과로 왕복 교통비
  계산). Recommend_place는 Search_Employee가 조회한 가족 구성(관계 필드)을 입력으로 쓰고,
  Price_Time·Nearby_Restaurant은 Recommend_place가 이미 계산해 반환한 명소 좌표(lat/lng)를
  그대로 재사용한다 — 좌표를 다시 조회하지 않는다.
- 외부 API 키: 카카오 디벨로퍼스 REST API 키(kakao.com developers, 로컬 API·다음 검색 API 공용 —
  Recommend_place와 Nearby_Restaurant이 같이 씀), 한국도로공사 공공데이터포털 API(data.go.kr
  인증키) — 전부 `.env`에서 읽는다.
- Recommend_place는 카카오 로컬 API 호출 시 `category_group_code=AT4`(관광명소 고정 코드)를
  요청 파라미터로 직접 넘겨 필터링한다 — 응답 문자열을 매칭하는 방식이 아니라서 이전에 네이버
  카테고리 문자열을 잘못 추측했던 것 같은 버그(0건만 반환)가 구조적으로 생기지 않는다.
- 가족 구성(관계: 배우자/아들/딸/기타 + 나이)에 따른 검색 키워드 분기(미성년 자녀 동반/커플/1인
  가구/그 외 가족여행 기본값), 동명이인 시 임직원ID 재확인, 지역 미입력 시 되묻기, 최종 답변에서
  가족 구성원 이름·나이·관계 마스킹은 전부 SERVICE.md 4번 가드레일에 정의돼 있다.
- 최종 답변 형식(임직원 이름을 넣은 인사 → 추천 명소와 추천 사유 → 맨 마지막에 '참고 자료' 표로
  주변 맛집·왕복 교통비·편도 소요시간 → 고정 안내 문구)도 SERVICE.md 4번에 정의돼 있으니 그대로
  따른다.

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다
