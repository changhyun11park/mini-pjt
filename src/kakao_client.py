"""kakao_client.py - 카카오 디벨로퍼스 API 공용 헬퍼 (인증 헤더, 블로그 언급 건수 조회).

tool_place.py(명소)와 tool_restaurant.py(맛집)가 함께 쓴다.
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

_BLOG_URL = "https://dapi.kakao.com/v2/search/blog"
_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

# 같은 명소·맛집 이름이 짧은 시간 안에 여러 번 조회되는 경우(같은 지역 반복 테스트,
# 추천 명소/그 외 가볼만한 곳 등)가 많아 언급 건수를 잠깐 캐싱해 카카오 API 호출을
# 줄인다. {name: (조회시각, 건수)}.
_mention_cache: dict[str, tuple[float, int]] = {}
_CACHE_TTL_SECONDS = 300


def kakao_headers() -> dict:
    return {"Authorization": f"KakaoAK {os.environ['KAKAO_REST_API_KEY']}"}


def blog_mention_count(name: str) -> int:
    """다음 검색 블로그 API로 "{name} 여행 후기"의 전체 검색결과 개수를 조회한다.

    5분 이내 같은 이름을 다시 조회하면 캐시된 값을 그대로 반환한다.
    """
    now = time.time()
    cached = _mention_cache.get(name)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    resp = requests.get(
        _BLOG_URL,
        headers=kakao_headers(),
        params={"query": f"{name} 여행 후기", "size": 1},
        timeout=10,
    )
    resp.raise_for_status()
    count = resp.json().get("meta", {}).get("total_count", 0)
    _mention_cache[name] = (now, count)
    return count


def to_latlng(item: dict) -> dict:
    # 카카오 로컬 API의 x/y는 그대로 경도/위도(십진수)라 별도 변환이 필요 없다.
    return {"lat": float(item["y"]), "lng": float(item["x"])}


def real_duration_min(a: dict, b: dict) -> int | None:
    """카카오모빌리티 길찾기(자동차) API로 두 좌표({"lat":..., "lng":...}) 사이
    실제 도로 기준 편도 소요시간(분)을 조회한다. 경로를 못 찾거나 호출에 실패하면
    None을 반환한다(이 경우 "가깝다고 확인되지 않음"으로 취급해 후보에서 제외한다).

    직선거리/평균속도 추정은 산·해안 등으로 우회하는 구간에서 실제 소요시간과 몇
    배씩 차이가 나서 폐기했다 — 반드시 실제 경로 조회로 판단한다. tool_place·
    tool_restaurant가 공용으로 쓴다.
    """
    try:
        resp = requests.get(
            _DIRECTIONS_URL,
            headers=kakao_headers(),
            params={
                "origin": f"{a['lng']},{a['lat']}",
                "destination": f"{b['lng']},{b['lat']}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        route = resp.json()["routes"][0]
        if route.get("result_code") != 0:
            return None
        return round(route["summary"]["duration"] / 60)
    except Exception:
        return None
