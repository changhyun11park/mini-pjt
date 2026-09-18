"""tool_restaurant.py - Nearby_Restaurant 도구: '추천 명소' 주변 맛집을 찾는다.

카카오 로컬 API의 카테고리 검색(좌표+반경, 음식점 고정 코드)으로 넉넉히 후보를
모은 뒤, 카카오모빌리티 길찾기(자동차) API로 실제 편도 소요시간을 조회해 '추천
명소' 기준 30분 이내인 곳만 추린다(직선거리 반경만으로는 실제 소요시간과 크게
어긋날 수 있어 recommend_place의 '그 외 가볼만한 곳'과 같은 방식으로 실측한다).
30분 이내에 하나도 없으면 60분 이내로 넓혀 같은 방식으로 다시 고른다.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from kakao_client import blog_mention_count, kakao_headers, real_duration_min, to_latlng

_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
_RESTAURANT_CATEGORY = "FD6"  # 카카오 로컬 API 카테고리 그룹 코드: 음식점
_SEARCH_RADIUS_M = 20000  # 카카오 로컬 API 반경 파라미터 최대값 — 넉넉히 모은 뒤 실제 소요시간으로 추린다
_CANDIDATE_POOL_SIZE = 15  # 카카오 로컬 API size 파라미터 최대값
_PRIMARY_MAX_MINUTES = 30
_FALLBACK_MAX_MINUTES = 60


def _nearby_search(lat: float, lng: float) -> list[dict]:
    resp = requests.get(
        _CATEGORY_URL,
        headers=kakao_headers(),
        params={
            "category_group_code": _RESTAURANT_CATEGORY,
            "x": lng,
            "y": lat,
            "radius": _SEARCH_RADIUS_M,
            "sort": "distance",
            "size": _CANDIDATE_POOL_SIZE,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("documents", [])


def _durations(origin: dict, items: list[dict]) -> list[int | None]:
    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        return list(pool.map(lambda it: real_duration_min(origin, to_latlng(it)), items))


def nearby_restaurant(lat: float, lng: float) -> str:
    """'추천 명소'의 좌표(recommend_place가 반환한 lat/lng를 그대로 넘김) 기준,
    실제 도로 편도 소요시간이 30분 이내인 맛집 중 언급 빈도가 가장 높은 곳
    하나를 추천한다(평점이 아니라 언급 빈도 기준). 30분 이내에 하나도 없으면
    60분 이내로 넓혀 같은 방식으로 다시 고른다.
    """
    origin = {"lat": lat, "lng": lng}
    items = _nearby_search(lat, lng)
    if not items:
        return json.dumps({"error": "주변에서 맛집을 찾을 수 없습니다."}, ensure_ascii=False)

    durations = _durations(origin, items)
    within = [
        it for it, minutes in zip(items, durations)
        if minutes is not None and minutes <= _PRIMARY_MAX_MINUTES
    ]
    if not within:
        within = [
            it for it, minutes in zip(items, durations)
            if minutes is not None and minutes <= _FALLBACK_MAX_MINUTES
        ]
    if not within:
        return json.dumps({"error": "주변에서 맛집을 찾을 수 없습니다."}, ensure_ascii=False)

    names = [it["place_name"] for it in within]
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        mention_counts = list(pool.map(blog_mention_count, names))

    ranked = [
        {
            "name": name,
            "address": it.get("road_address_name") or it.get("address_name", ""),
            "mention_count": count,
            "url": it.get("place_url", ""),
        }
        for it, name, count in zip(within, names, mention_counts)
    ]
    ranked.sort(key=lambda x: x["mention_count"], reverse=True)

    result = {
        "note": "평점이 아니라 최근 블로그 언급이 많은 곳 기준입니다.",
        "추천_맛집": ranked[0],
    }
    return json.dumps(result, ensure_ascii=False)
