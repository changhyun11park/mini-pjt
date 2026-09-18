"""tool_place.py - Recommend_place 도구: 지역+가족 구성으로 명소를 추천한다.

카카오 디벨로퍼스 API(로컬 API + 다음 검색 블로그 API)만 사용한다 — REST API 키 하나로
둘 다 호출 가능하고, 완전 무료로 즉시 발급된다.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from kakao_client import blog_mention_count, kakao_headers, real_duration_min, to_latlng
from region_validator import validate_region

_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
_TOURIST_SPOT_CATEGORY = "AT4"  # 카카오 로컬 API 카테고리 그룹 코드: 관광명소

# 가족 구성 유형별로 실제 검색해볼 구체적인 키워드를 둔다. 유형마다 서로 다른 명소
# 후보군이 모이게 해서, 지역이 같아도 가족 구성에 따라 추천이 달라지게 한다(형용사
# 하나만 쓰면 카카오 키워드 검색이 지역 전체에서 가장 유명한 곳으로 수렴해버려 가족
# 구성과 무관하게 항상 같은 곳만 추천되는 문제가 있었다). 키워드는 2개까지만 써서
# 카카오 API 호출·응답 대기 시간이 지나치게 늘어나지 않게 한다.
_FAMILY_KEYWORD_POOL = {
    "child": ["아이랑 가볼만한", "키즈카페"],
    "couple": ["커플 여행", "카페거리"],
    "solo": ["혼자 가기 좋은", "산책로"],
    "family": ["가족여행", "체험마을"],
}
_FAMILY_LABEL = {
    "child": "아이와 가볼만한",
    "couple": "커플 여행",
    "solo": "혼자 가기 좋은",
    "family": "가족여행",
}
# 후보 하나가 풀의 여러 키워드에 동시에 걸릴 수 있는데(예: "아이랑 가볼만한"과
# "키즈카페" 둘 다), 처음 만난 키워드(=풀에서 더 앞쪽, 그 가족 구성을 가장
# 직접적으로 표현하는 키워드) 기준으로만 가족 적합도를 매긴다. 풀의 첫 키워드에
# 걸리면 1.0(적합도 최고), 두 번째(더 넓은 보조 키워드)에만 걸리면 0.6, 두 키워드
# 검색이 모두 0건이라 지역명만으로 재검색한 후보는 가족 적합도를 알 수 없어 0.0.
_PRIMARY_FIT = 1.0
_SECONDARY_FIT = 0.6
_FALLBACK_FIT = 0.0
_MAX_CANDIDATES = 10  # 키워드 2개(각 size=5) 검색 결과를 합친 뒤 적용하는 안전 상한

# 카카오 키워드 검색은 "혼자 가기 좋은"·"커플 여행" 같은 수식어를 넣어도 문자열
# 매칭이라 그 지역에서 가장 언급이 많은 동물원·키즈카페 같은 곳이 검색어와 무관하게
# 계속 섞여 들어온다(예: "완산구 산책로" 검색에도 "전주동물원"이 나옴). 언급 건수가
# 압도적으로 높으면 50:50 가중치만으론 걸러지지 않으므로, 자녀 없는 1인 가구·커플에는
# 이런 이름의 후보를 점수 계산 전에 아예 제외한다(후보가 하나도 안 남으면 어쩔 수
# 없이 원래 목록을 그대로 쓴다).
_CHILD_ORIENTED_NAME_KEYWORDS = ["키즈", "동물원", "체험"]
_NO_CHILD_FAMILY_TYPES = ("solo", "couple")


def _is_child_oriented(place_name: str) -> bool:
    return any(kw in place_name for kw in _CHILD_ORIENTED_NAME_KEYWORDS)

# "함께 가볼 곳" 후보를 '추천 명소'에서 얼마나 가까운 것까지 인정할지(편도 소요시간).
# 실제 도로 기준 편도 소요시간 조회는 kakao_client.real_duration_min(공용)을 쓴다.
_NEARBY_MAX_MINUTES = 30
_NEARBY_MAX_CANDIDATES = 2


def _family_type(family: list[dict]) -> str:
    """가족 구성(관계 필드)으로 검색 유형을 정한다.

    미성년 자녀가 있으면 "child", 배우자만 있으면(커플) "couple",
    구성원이 없으면(1인 가구) "solo", 그 외(성인 자녀만 있는 가족 등)는 "family".
    """
    if not family:
        return "solo"
    has_minor_child = any(m["relation"] in ("아들", "딸") and m["age"] < 19 for m in family)
    if has_minor_child:
        return "child"
    only_spouse = len(family) == 1 and family[0]["relation"] == "배우자"
    if only_spouse:
        return "couple"
    return "family"


def _local_search(query: str) -> list[dict]:
    resp = requests.get(
        _LOCAL_URL,
        headers=kakao_headers(),
        params={"query": query, "category_group_code": _TOURIST_SPOT_CATEGORY, "size": 5},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("documents", [])


def recommend_place(region: str, family: list[dict]) -> str:
    """담당자가 입력한 지역(정확한 목적지 또는 넓은 지역)과 가족 구성으로 명소를
    검색한다. 순위는 가족 구성 적합도와 최근 블로그 언급 빈도를 각각 50%씩 반영한
    점수로 매긴다 — 언급 건수만 보면 지역에서 가장 유명한 곳으로 수렴해 가족 구성과
    무관하게 항상 같은 곳만 추천되던 문제를 보완한다. 자녀 없는 1인 가구·커플에는
    이름에 "키즈"·"동물원"·"체험"이 들어간 후보를 점수 계산 전에 제외한다 —
    언급 건수가 워낙 높아 50:50 가중치만으론 안 걸러지는 경우가 있어서다.

    family는 Search_Employee가 반환한 family 리스트를 그대로 넘긴다.
    지역 없이는 호출하지 않는다 — 지역이 없으면 먼저 담당자에게 되물어야 한다.

    그_외_가볼만한_곳은 추천_명소 기준 편도 30분 이내(카카오모빌리티 길찾기 API로 실제
    도로 기준 조회)인 후보만 최대 2곳 담는다 — 답변의 '함께 가볼 곳' 섹션에 쓴다.

    북한 지역, 국내 고속도로로 갈 수 없는 해외 지역, 실존하지 않는 지역명이면
    invalid_region:true와 함께 이유(reason)·안내 문구(message)를 반환하니, 이
    경우 그 문구를 그대로 전달하고 다른 지역명을 다시 물어봐야 한다.
    """
    invalid = validate_region(region)
    if invalid:
        return json.dumps(invalid, ensure_ascii=False)

    family_type = _family_type(family)
    keyword_label = _FAMILY_LABEL[family_type]

    items: list[dict] = []
    fit_by_key: dict[tuple[str, str], float] = {}
    seen = set()
    for tier_fit, kw in zip((_PRIMARY_FIT, _SECONDARY_FIT), _FAMILY_KEYWORD_POOL[family_type]):
        for it in _local_search(f"{region} {kw}"):
            key = (it["place_name"], it.get("address_name", ""))
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
            fit_by_key[key] = tier_fit
    items = items[:_MAX_CANDIDATES]
    if family_type in _NO_CHILD_FAMILY_TYPES:
        kid_free = [it for it in items if not _is_child_oriented(it["place_name"])]
        if kid_free:
            items = kid_free
    if not items:
        items = _local_search(region)
        for it in items:
            fit_by_key[(it["place_name"], it.get("address_name", ""))] = _FALLBACK_FIT
    if not items:
        return json.dumps({"error": "일치하는 명소를 찾을 수 없습니다."}, ensure_ascii=False)

    names = [it["place_name"] for it in items]
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        mention_counts = list(pool.map(blog_mention_count, names))

    # 언급 건수는 후보마다 값의 범위가 크게 달라(수십~수십만) 그대로 더하면 가족
    # 적합도(0~1)와 비중을 맞출 수 없다 — 이번 후보군 안에서 최소~최대로 0~1로
    # 정규화한 뒤에만 50:50으로 더한다.
    max_mention = max(mention_counts, default=0)
    min_mention = min(mention_counts, default=0)
    mention_span = max_mention - min_mention

    def _mention_score(count: int) -> float:
        return (count - min_mention) / mention_span if mention_span else 1.0

    def _combined_score(pair: tuple[dict, int]) -> float:
        it, count = pair
        fit = fit_by_key.get((it["place_name"], it.get("address_name", "")), _FALLBACK_FIT)
        return 0.5 * fit + 0.5 * _mention_score(count)

    triples = sorted(zip(items, mention_counts), key=_combined_score, reverse=True)

    ranked = [
        {
            "name": it["place_name"],
            "address": it.get("road_address_name") or it.get("address_name", ""),
            "mention_count": count,
            "url": it.get("place_url", ""),
            **to_latlng(it),
        }
        for it, count in triples
    ]

    top_place = ranked[0]
    other_candidates = ranked[1:]
    if other_candidates:
        with ThreadPoolExecutor(max_workers=len(other_candidates)) as pool:
            durations = list(pool.map(lambda cand: real_duration_min(top_place, cand), other_candidates))
    else:
        durations = []

    nearby = [
        {**cand, "duration_min": duration_min}
        for cand, duration_min in zip(other_candidates, durations)
        if duration_min is not None and duration_min <= _NEARBY_MAX_MINUTES
    ]
    nearby = nearby[:_NEARBY_MAX_CANDIDATES]

    result = {
        "keyword_used": keyword_label,
        "note": "평점이 아니라 가족 구성 적합도와 최근 블로그 언급 빈도를 각각 50%씩 반영한 순위입니다.",
        "추천_명소": top_place,
        # '추천 명소'에서 편도 30분 이내인 곳만 추린 목록 — '함께 가볼 곳'으로 답변에 쓴다.
        "그_외_가볼만한_곳": nearby,
    }
    return json.dumps(result, ensure_ascii=False)
