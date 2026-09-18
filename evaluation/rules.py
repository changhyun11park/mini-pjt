"""rules.py - SERVICE.md 4/5번의 규칙 중, 실행 결과(raw contexts)만 있으면 사람 없이도
기계적으로 채점 가능한 항목만 모아 둔 체크 함수 모음.

각 check_* 함수는 (통과 여부, 실패 이유) 튜플의 리스트를 반환한다. 문장의 자연스러움·
추천 사유의 매력도처럼 사람이 봐야 하는 부분은 여기서 다루지 않는다 — evaluation/report.md를
사람이 직접 읽고 판단한다.
"""
import json
import os
import re

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_EMPLOYEES_PATH = os.path.join(_BASE_DIR, "..", "data", "employee.json")

with open(_EMPLOYEES_PATH, encoding="utf-8") as f:
    EMPLOYEES = json.load(f)

FUEL_COST_PER_KM = 150

NORTH_KOREA_MESSAGE = "해당 지역은 여행이 불가합니다. 국내 다른 지역으로 다시 알려주시겠어요?"
OVERSEAS_MESSAGE = (
    "거리가 멀어 주말 동안 다녀오시기 어려울 수 있어요. "
    "국내 여행지로 선택해보시는 건 어떨까요?"
)
REGION_NOT_FOUND_MESSAGE = "입력하신 지역명을 찾을 수 없습니다. 지역명을 다시 확인해 주시겠어요?"

FOOTER_COST_NOTE = "고속도로 통행료와 유류비를 포함한 추정치"
FOOTER_RANKING_NOTE = "가족 구성 적합도와 최근 블로그 언급 빈도"


def _contexts_by_tool(contexts: list[dict]) -> dict:
    return {c["tool"]: c["result"] for c in contexts}


def expected_keyword_label(family: list[dict]) -> str:
    """tool_place._family_type / _FAMILY_LABEL 로직을 독립적으로 재구현한다.

    recommend_place가 실제로 반환한 keyword_used와 대조해, 가족 구성 분기 로직
    자체에 버그가 있어도 여기서 잡아낸다(같은 코드를 그대로 import해서 비교하면
    도구 쪽 버그를 놓친다).
    """
    if not family:
        return "혼자 가기 좋은"
    has_minor_child = any(m["relation"] in ("아들", "딸") and m["age"] < 19 for m in family)
    if has_minor_child:
        return "아이와 가볼만한"
    if len(family) == 1 and family[0]["relation"] == "배우자":
        return "커플 여행"
    return "가족여행"


def check_unregistered_employee(case: dict, result: dict) -> list[tuple[bool, str]]:
    expected = f"'{case['employee']}' 임직원을 찾을 수 없습니다."
    ok = result["answer"] == expected
    return [(ok, f"미등록 임직원 안내문 불일치: 기대={expected!r} 실제={result['answer']!r}" if not ok else "")]


def check_unregistered_region(case: dict, result: dict) -> list[tuple[bool, str]]:
    ok = result["answer"] == REGION_NOT_FOUND_MESSAGE
    return [(ok, f"미등록 지역 안내문 불일치: 실제={result['answer']!r}" if not ok else "")]


def check_north_korea(case: dict, result: dict) -> list[tuple[bool, str]]:
    ok = result["answer"] == NORTH_KOREA_MESSAGE
    return [(ok, f"북한 지역 안내문 불일치: 실제={result['answer']!r}" if not ok else "")]


def check_overseas(case: dict, result: dict) -> list[tuple[bool, str]]:
    ok = result["answer"] == OVERSEAS_MESSAGE
    return [(ok, f"해외 지역 안내문 불일치: 실제={result['answer']!r}" if not ok else "")]


def check_ambiguous_employee(case: dict, result: dict) -> list[tuple[bool, str]]:
    checks = []
    answer = result["answer"]
    checks.append(("동명이인" in answer, "answer에 '동명이인' 표현이 없음" if "동명이인" not in answer else ""))

    contexts = _contexts_by_tool(result["contexts"])
    emp_result = contexts.get("search_employee", {})
    checks.append((emp_result.get("ambiguous") is True, "search_employee 결과가 ambiguous:true가 아님"))

    real_matches = [e for e in EMPLOYEES if e["name"] == case["employee"]]
    real_ids = {e["id"] for e in real_matches}
    returned_ids = {c["id"] for c in emp_result.get("candidates", [])}
    checks.append((
        real_ids == returned_ids,
        f"후보 임직원ID 불일치(지어냈거나 빠짐): 실제 등록={real_ids} 응답={returned_ids}",
    ))
    for c in emp_result.get("candidates", []):
        present = c["id"] in answer and c["name"] in answer
        checks.append((present, f"answer에 후보 {c['name']}({c['id']}) 정보가 없음"))
    return checks


def check_normal_case(case: dict, result: dict) -> list[tuple[bool, str]]:
    """정상 케이스(목적지 확정): 공식 계산·마스킹·답변 형식을 raw contexts 대비 검증한다."""
    checks: list[tuple[bool, str]] = []
    answer = result["answer"]
    contexts = _contexts_by_tool(result["contexts"])

    employee = contexts.get("search_employee", {})
    family = employee.get("family", [])

    place = contexts.get("recommend_place", {})
    if "error" in place or "추천_명소" not in place:
        ok = answer == place.get("error", "일치하는 명소를 찾을 수 없습니다.")
        checks.append((ok, "명소 0건일 때 데이터 없음 안내가 그대로 나오지 않음"))
        return checks

    # 1) 가족 구성 -> 검색 키워드 분기
    expected_label = expected_keyword_label(family)
    actual_label = place.get("keyword_used")
    checks.append((
        expected_label == actual_label,
        f"가족 구성({family}) 기준 기대 키워드={expected_label!r}, recommend_place 실제={actual_label!r}",
    ))

    # 2) 왕복 교통비 공식: (통행료 + 거리 x 유류비) x 2, raw price_time 값 기준
    price = contexts.get("price_time", {})
    calc = contexts.get("traffic_calculator", {})
    if "toll" in price and "distance_km" in price and "round_trip_cost" in calc:
        expected_cost = round((price["toll"] + price["distance_km"] * FUEL_COST_PER_KM) * 2)
        checks.append((
            expected_cost == calc["round_trip_cost"],
            f"traffic_calculator 계산값 불일치: 기대={expected_cost} 실제={calc['round_trip_cost']}",
        ))
        answer_numbers = {int(n.replace(",", "")) for n in re.findall(r"[\d][\d,]*", answer)}
        checks.append((
            expected_cost in answer_numbers,
            f"answer 안 참고 자료 표에 왕복 교통비 {expected_cost}원이 그대로 안 보임",
        ))
    else:
        checks.append((False, "price_time/traffic_calculator 결과에 toll/distance_km/round_trip_cost가 없음"))

    # 3) 편도 소요시간은 duration_display 문자열을 그대로 써야 한다(분 단위 재환산 금지)
    duration_display = price.get("duration_display")
    if duration_display:
        checks.append((
            duration_display in answer,
            f"answer에 duration_display({duration_display!r})가 그대로 없음",
        ))

    # 4) 가족 구성원 이름·나이 마스킹 (본인 이름은 노출 가능)
    for member in family:
        name = member.get("name", "")
        if len(name) > 1:
            checks.append((name not in answer, f"가족 구성원 실명 '{name}'이 answer에 그대로 노출됨"))
        age = member.get("age")
        if age is not None:
            leaked = re.search(rf"{age}\s*(세|살)", answer) is not None
            checks.append((not leaked, f"가족 구성원 나이 '{age}세/살'이 answer에 노출됨"))

    # 5) 섹션 구성: 추천 명소 / (있으면) 함께 가볼 곳 / 주변 맛집 / 참고 자료(표, 2행, 순서)
    # SERVICE.md 4번: 이름이 등장하는 자리(소제목 또는 굵은 라벨)에 place_url이 있으면
    # 코드(link_section.linkify_places)가 그 자리에 마크다운 링크를 걸어야 한다.
    def _named(name: str, url: str | None) -> str:
        return f"[{name}]({url})" if url else name

    top_place = place["추천_명소"]
    top_named = _named(top_place["name"], top_place.get("url"))
    checks.append((top_named in answer, f"추천 명소 '{top_place['name']}'이 '{top_named}' 형태로 없음"))

    nearby = place.get("그_외_가볼만한_곳", [])
    if not nearby:
        checks.append(("함께 가볼 곳" not in answer, "함께 가볼 곳 후보가 없는데 섹션이 남아 있음"))
    elif len(nearby) == 1:
        cand = nearby[0]
        heading = f"### 🧭 함께 가볼 곳: {_named(cand['name'], cand.get('url'))}"
        checks.append((heading in answer, f"후보 1곳일 때 소제목이 '{heading}' 형태가 아님"))
    else:
        checks.append(("함께 가볼 곳" in answer, "함께 가볼 곳 후보가 있는데 해당 섹션이 없음"))
        for cand in nearby:
            marker = f"**{_named(cand['name'], cand.get('url'))}**"
            checks.append((marker in answer, f"함께 가볼 곳 후보 '{cand['name']}'이 '{marker}' 형태로 없음"))

    checks.append(("주변 맛집" in answer, "주변 맛집 섹션 헤더가 없음"))
    restaurant = contexts.get("nearby_restaurant", {}).get("추천_맛집")
    if restaurant:
        heading = f"### 🍽️ 주변 맛집: {_named(restaurant['name'], restaurant.get('url'))}"
        checks.append((heading in answer, f"주변 맛집 소제목이 '{heading}' 형태가 아님"))
        checks.append((restaurant["address"] in answer, f"주변 맛집 주소 '{restaurant['address']}'가 answer에 없음"))
    else:
        checks.append(("데이터 없음" in answer, "맛집 조회가 0건인데 '데이터 없음' 표기가 없음"))

    # 5b) 링크는 소제목/굵은 라벨 자리에만 있어야 한다 — 인사말(첫 소제목 이전)에
    # URL이 보이면 linkify_places가 엉뚱한 자리(예: 인사말)에 링크를 건 것이다.
    first_heading = answer.find("###")
    greeting = answer[:first_heading] if first_heading != -1 else answer
    checks.append((
        "http://" not in greeting and "https://" not in greeting,
        "인사말(첫 소제목 이전)에 URL/링크가 노출됨 — linkify_places가 엉뚱한 자리에 링크를 걺",
    ))

    checks.append(("참고 자료" in answer, "참고 자료 섹션 헤더가 없음"))
    checks.append(("왕복 교통비" in answer, "참고 자료 표에 '왕복 교통비' 행이 없음"))
    checks.append(("편도 소요시간" in answer, "참고 자료 표에 '편도 소요시간' 행이 없음"))
    if "왕복 교통비" in answer and "편도 소요시간" in answer:
        checks.append((
            answer.index("왕복 교통비") < answer.index("편도 소요시간"),
            "참고 자료 표 행 순서가 (왕복 교통비, 편도 소요시간)이 아님",
        ))

    # 6) 고정 안내 문구 두 줄
    checks.append((FOOTER_COST_NOTE in answer, "교통비 추정치 고정 안내 문구가 없음"))
    checks.append((FOOTER_RANKING_NOTE in answer, "블로그 언급 빈도 고정 안내 문구가 없음"))

    # 7) 참고 자료 표가 답변의 마지막 내용이어야 한다 — LLM이 표 뒤에 링크 등
    # 요청하지 않은 섹션을 덧붙이면 "###" 헤딩 개수가 기대치를 넘어선다.
    expected_headings = 3 + (1 if nearby else 0)  # 추천 명소 + (함께 가볼 곳) + 주변 맛집 + 참고 자료
    actual_headings = answer.count("###")
    checks.append((
        actual_headings <= expected_headings,
        f"참고 자료 표 뒤에 예상치 못한 섹션이 덧붙어 있음(### 헤딩 {actual_headings}개, 기대 {expected_headings}개 이하)",
    ))

    return checks


CATEGORY_CHECKERS = {
    "미등록_임직원": check_unregistered_employee,
    "미등록_지역": check_unregistered_region,
    "동명이인": check_ambiguous_employee,
    "북한지역": check_north_korea,
    "해외지역": check_overseas,
}


def check(case: dict, result: dict) -> list[tuple[bool, str]]:
    """case(csv 한 행)와 result(run_eval.py가 저장한 answer/contexts/trace)로 규칙을 검사한다."""
    for prefix, fn in CATEGORY_CHECKERS.items():
        if case["category"].startswith(prefix):
            return fn(case, result)
    if case["category"].startswith("정상_"):
        return check_normal_case(case, result)
    raise ValueError(f"알 수 없는 category: {case['category']}")
