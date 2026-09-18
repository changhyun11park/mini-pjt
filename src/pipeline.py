"""pipeline.py - 결정적 도구 호출 체인.

search_employee -> recommend_place -> price_time·nearby_restaurant(병렬) ->
traffic_calculator 순서는 애초에 분기가 없는 고정 순서다(SERVICE.md 3번). 그런데도
지금까지는 이 순서를 create_agent의 ReAct 루프가 매 단계마다 "다음에 뭘 부를지"
LLM에게 되물어 왔다 — 이 파일은 그 순서를 파이썬 코드로 그대로 고정해서 실행하고,
LLM은 다 모은 데이터를 자연스러운 문장으로 다듬는 마지막 한 번만 부른다. Bedrock
호출이 4~5회에서 1회로 줄어 응답 시간이 크게 단축된다.

동명이인·미등록 임직원·지역 가드레일은 fast_path.py가 이미 걸러내므로, 이 모듈에
들어올 때는 항상 임직원 1명 + 유효한 지역이 확정된 상태다. 다만 지역은 유효한데
실제 후보 명소가 0건인 경우(recommend_place 자체 에러)는 이 안에서도 방어적으로
처리한다.
"""
import json
from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import HumanMessage, SystemMessage

from link_section import linkify_places, strip_markdown_links, truncate_after_table
from masking import mask_family_info, to_text
from tool_place import recommend_place
from tool_price_time import price_time
from tool_restaurant import nearby_restaurant
from tool_traffic_calculator import traffic_calculator

ANSWER_FOOTER = (
    "\n\n"
    '<div class="answer-footnote">'
    "※ 위 교통비는 고속도로 통행료와 유류비를 포함한 추정치 입니다.<br>"
    "※ 명소 추천 근거는 평점이 아니라 가족 구성 적합도와 최근 블로그 언급 빈도입니다."
    "</div>"
)

_COMPOSE_SYSTEM_PROMPT = (
    "너는 삼성SDS 인사팀 담당자를 돕는 주말 여행지 추천 Agent다. 사람이 보낸 메시지의\n"
    "[조회된 데이터]는 이미 실제 조회를 마친 결과이니 그대로 사용하고, 다른 명소나\n"
    "수치로 바꾸거나 새로 지어내지 않는다.\n"
    "\n"
    "[답변 형식]\n"
    "대상 임직원 이름을 넣어 한 주간 고생했다는 인사로 시작한다. 인사말과 추천 사유의\n"
    "어투는 [조회된 데이터]의 '가족 구성 유형'에 맞춰 다르게 쓴다:\n"
    "- '혼자 가기 좋은'(1인 가구)이면 가족을 전혀 언급하지 않는다. '가족과 함께' 대신\n"
    "  '혼자 여유롭게'처럼 표현하고, 추천 사유도 아이 동반·가족 나들이 같은 표현 없이\n"
    "  혼자서 즐기기 좋은 점(여유·힐링·자유로움 등)을 강조한다.\n"
    "- '커플 여행'(배우자만 있음)이면 '배우자님과 함께'를 언급하고, 추천 사유도 커플이\n"
    "  즐기기 좋은 점(분위기·함께 즐길 거리 등)을 강조한다.\n"
    "- '아이와 가볼만한'(미성년 자녀 있음)이면 가족 구성원(배우자님, 아드님·따님 등)과\n"
    "  함께를 언급하고, 추천 사유도 아이와 함께 즐기기 좋은 점을 강조한다.\n"
    "- '가족여행'(그 외, 성인 자녀만 있는 가족 등)이면 '가족과 함께'를 언급하고, 추천\n"
    "  사유도 가족 모두가 즐기기 좋은 점을 강조한다.\n"
    "이번 주말 추천 명소로 다녀올 것을 권유한다. 인사말 다음 줄에 추천 명소 이름을\n"
    "소제목으로 띄운다(예: '### 🏞️ 이번 주 추천: {명소명}'). 이모지는 인사말과 이\n"
    "소제목에 하나씩 정도만 자연스럽게 쓰고 과하게 넣지 않는다. 추천 사유는 위 어투\n"
    "기준에 맞춰 분위기·볼거리·함께 즐길 거리 등을 자연스럽고 가고 싶은 마음이 들도록\n"
    "표현하고, 블로그 언급 건수 같은 구체적인 숫자는 답변에 적지 않는다.\n"
    "추천 명소 설명 다음에는 [조회된 데이터]의 함께 가볼 곳 후보로 '이번 주 추천'과\n"
    "같은 수준(###)의 소제목을 하나 더 쓴다. 이모지는 하나 정도만 자연스럽게 쓴다.\n"
    "후보가 없으면 이 섹션 전체를 쓰지 않는다. 후보가 1곳이면 '### 🧭 함께 가볼 곳:\n"
    "{장소명}'처럼 이름을 소제목에 넣고, 그 아래에 함께 가볼 만한 이유를 '이번 주\n"
    "추천'처럼 문단으로 설명한다. 후보가 2곳이면 '### 🧭 함께 가볼 곳'이라는 소제목만\n"
    "쓰고, 그 아래에 각 후보를 '**{장소명}**: {함께 가볼 만한 이유}' 형태로 이름과\n"
    "설명을 콜론(:)으로 이어 한 줄씩 쓴다. 두 경우 모두 소요시간·거리 같은 구체적인\n"
    "숫자는 적지 않는다.\n"
    "그다음 같은 수준(###)으로 주변 맛집 섹션을 쓴다. [조회된 데이터]에 맛집이 있으면\n"
    "'### 🍽️ 주변 맛집: {맛집명}'처럼 이름을 소제목에 넣고, 그 아래에 주소를 적는다.\n"
    "맛집이 없으면 '### 🍽️ 주변 맛집' 소제목만 쓰고 그 아래에 '데이터 없음'이라고\n"
    "적는다(이 소제목 자체는 생략하지 않는다).\n"
    "교통비·소요시간은 본문이 아니라 맨 마지막에 '### 📋 참고 자료'처럼 이모지를\n"
    "하나 곁들인 소제목 아래 마크다운 표(테이블)로 정리한다 — 표의 행은 반드시 이\n"
    "순서로, 이 두 행만 쓴다: 1) '왕복 교통비'(약 OO원) 2) '편도 소요시간'([조회된\n"
    "데이터]의 편도 소요시간 값을 그대로 적는다 — 분 단위로 직접 환산하지 않는다).\n"
    "주변 맛집은 표에 넣지 않는다.\n"
    "\n"
    "[반드시 지킬 것]\n"
    "- 표를 쓰고 나면 답변을 그 자리에서 즉시 끝낸다. 표 뒤에는 문장이든 인용구든\n"
    "  안내 문구든 그 어떤 내용도 절대 덧붙이지 않는다 — 안내 문구는 시스템이 표 뒤에\n"
    "  자동으로 붙인다.\n"
    "- 명소·맛집 이름 옆에 마크다운 링크나 http(s) 주소를 직접 쓰지 않는다. 이름은\n"
    "  항상 평문으로만 쓴다 — 실제 링크는 답변이 완성된 뒤 시스템이 코드로 정확한\n"
    "  자리에 자동으로 붙인다.\n"
    "- [조회된 데이터]에 없는 명소·수치는 지어내지 않는다.\n"
    "- 가족 구성원은 성이든 이름만이든 실제 이름으로 절대 부르지 않는다. 항상 관계로만\n"
    "  지칭한다(예: 배우자님, 아드님, 따님). 대상 임직원 본인 이름만 답변에 써도 된다.\n"
    "- 가족 구성원의 나이도 답변에 절대 언급하지 않는다. 숫자('6세')든 한글 숫자\n"
    "  ('여섯 살')든 나이를 알 수 있는 표현은 어떤 형태로도 쓰지 않는다.\n"
)


def _run_place_dependent_tools(place: dict) -> tuple[str, str]:
    """price_time과 nearby_restaurant은 서로 독립적이라 동시에 실행한다."""
    lat, lng, name = place["lat"], place["lng"], place["name"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        price_future = pool.submit(price_time, lat, lng, name)
        restaurant_future = pool.submit(nearby_restaurant, lat, lng)
        return price_future.result(), restaurant_future.result()


def _restaurant_line(restaurant: dict) -> str:
    r = restaurant.get("추천_맛집")
    if not r:
        return "데이터 없음"
    return f"{r['name']} ({r['address']})"


def _nearby_line(nearby: list[dict]) -> str:
    if not nearby:
        return "없음"
    return ", ".join(f"{n['name']} ({n['address']})" for n in nearby)


async def run(employee: dict, region: str, llm) -> dict:
    """employee(단일 임직원 레코드)와 유효한 region으로 나머지 도구를 고정 순서로
    실행하고, 마지막에 LLM을 1번만 불러 답변 문장을 완성한다."""
    name = employee["name"]
    family = employee.get("family", [])

    place_raw = recommend_place(region, family)
    place = json.loads(place_raw)

    contexts = [
        {"tool": "search_employee", "result": employee},
        {"tool": "recommend_place", "result": place},
    ]
    trace = [
        {"seq": 1, "type": "tool_call", "name": "search_employee", "args": {"name_or_id": name}},
        {"seq": 2, "type": "tool_result", "name": "search_employee", "content": json.dumps(employee, ensure_ascii=False)},
        {"seq": 3, "type": "tool_call", "name": "recommend_place", "args": {"region": region, "family": family}},
        {"seq": 4, "type": "tool_result", "name": "recommend_place", "content": place_raw},
    ]

    # region_validator를 통과했더라도 실제 후보가 0건일 수 있다(예: 아주 좁은 지역명) —
    # 이 경우는 지어내지 않고 그대로 '데이터 없음'을 안내하며, LLM 호출 없이 끝낸다.
    if "error" in place or "추천_명소" not in place:
        answer = place.get("error", "일치하는 명소를 찾을 수 없습니다.")
        trace.append({"seq": 5, "type": "answer", "content": answer})
        return {"answer": answer, "contexts": contexts, "trace": trace}

    top_place = place["추천_명소"]
    price_raw, restaurant_raw = _run_place_dependent_tools(top_place)
    price = json.loads(price_raw)
    restaurant = json.loads(restaurant_raw)
    calc_raw = traffic_calculator(price["toll"], price["distance_km"])
    calc = json.loads(calc_raw)

    contexts += [
        {"tool": "price_time", "result": price},
        {"tool": "nearby_restaurant", "result": restaurant},
        {"tool": "traffic_calculator", "result": calc},
    ]
    trace += [
        {"seq": 5, "type": "tool_call", "name": "price_time", "args": {"dest_lat": top_place["lat"], "dest_lng": top_place["lng"], "dest_name": top_place["name"]}},
        {"seq": 5, "type": "tool_call", "name": "nearby_restaurant", "args": {"lat": top_place["lat"], "lng": top_place["lng"]}},
        {"seq": 6, "type": "tool_result", "name": "price_time", "content": price_raw},
        {"seq": 7, "type": "tool_result", "name": "nearby_restaurant", "content": restaurant_raw},
        {"seq": 8, "type": "tool_call", "name": "traffic_calculator", "args": {"toll": price["toll"], "distance_km": price["distance_km"]}},
        {"seq": 9, "type": "tool_result", "name": "traffic_calculator", "content": calc_raw},
    ]

    human = (
        "[조회된 데이터]\n"
        f"대상 임직원: {name}\n"
        f"가족 구성: {json.dumps(family, ensure_ascii=False)}\n"
        f"가족 구성 유형: {place['keyword_used']}\n"
        f"추천 명소: {top_place['name']} ({top_place['address']})\n"
        f"함께 가볼 곳 후보: {_nearby_line(place.get('그_외_가볼만한_곳', []))}\n"
        f"주변 맛집: {_restaurant_line(restaurant)}\n"
        f"편도 거리: {price['distance_km']}km\n"
        f"편도 소요시간: {price['duration_display']}\n"
        f"왕복 교통비: {calc['round_trip_cost']}원\n"
        "\n위 데이터를 바탕으로 [답변 형식]에 맞는 답변을 작성해줘."
    )
    response = await llm.ainvoke([
        SystemMessage(content=_COMPOSE_SYSTEM_PROMPT),
        HumanMessage(content=human),
    ])
    text = to_text(response.content)
    text = truncate_after_table(text)
    if family:
        text = mask_family_info(text, family)
    text = strip_markdown_links(text)
    text = linkify_places(text, place, restaurant)
    text = text + ANSWER_FOOTER

    trace.append({"seq": 10, "type": "answer", "content": text})
    return {"answer": text, "contexts": contexts, "trace": trace}
