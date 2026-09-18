"""tool_price_time.py - Price_Time 도구: '추천 명소' 기준 통행료·거리·소요시간을 조회한다.

통행료는 한국도로공사 공공데이터포털 "영업소간 통행요금 조회" API를 쓴다 (data.go.kr,
완전 무료 — 개발단계는 자동승인). 도착지는 좌표만 알면 되므로, 출발지(삼성SDS 본사)에서
가장 가까운 영업소와 도착지(추천 명소)에서 가장 가까운 영업소를 직선거리로 계산해 찾는다.
이 API의 소요시간은 두 영업소 사이 고속도로 구간만 포함해 실제보다 짧게 나오므로,
편도 소요시간은 대신 카카오모빌리티 길찾기(자동차) API로 삼성SDS 본사에서 추천 명소까지
실제 도로 기준으로 직접 조회한다(다른 구간을 더하지 않은, 문 앞에서 문 앞까지의 값).
"""
import json
import math
import os

import requests
from dotenv import load_dotenv

from kakao_client import kakao_headers

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIONS_PATH = os.path.join(_BASE_DIR, "..", "data", "Ex_Office_Coor.json")

with open(_STATIONS_PATH, encoding="utf-8") as f:
    STATIONS: list[dict] = json.load(f)

# 삼성SDS타워WESTCAMPUS 근사 좌표 (고정값)
OFFICE_LAT, OFFICE_LNG = 37.5133, 127.1000

FUEL_COST_PER_KM = 150  # 원/km 고정 단가 (연료비 추정용)

# 한국도로공사 공공데이터포털 "영업소간 통행요금 조회" API (bhoinstIntoTollList)
_TOLL_API_URL = "https://data.ex.co.kr/openapi/toll/bhoinstIntoTollList"
# 카카오모빌리티 길찾기(자동차) API — 편도 소요시간은 이 실제 경로 조회 결과를 쓴다.
_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest_station(lat: float, lng: float) -> dict:
    """전국 영업소 좌표 목록 중 직선거리가 가장 가까운 영업소를 찾는다."""
    return min(STATIONS, key=lambda s: _haversine_km(lat, lng, s["위도"], s["경도"]))


_ORIGIN_STATION = _nearest_station(OFFICE_LAT, OFFICE_LNG)  # 모듈 로드 시 1회 계산, 고정


def _format_duration(duration_min: int) -> str:
    """분을 'N시간 M분' 형태로 바꾼다(1시간 미만이면 분만 표시)."""
    hours, minutes = divmod(duration_min, 60)
    if hours > 0:
        return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"
    return f"{minutes}분"


def _office_to_dest_duration_min(dest_lat: float, dest_lng: float) -> int | None:
    """카카오모빌리티 길찾기로 삼성SDS 본사에서 추천 명소까지 실제 도로 기준 편도
    소요시간(분)을 조회한다. 경로를 못 찾거나 호출에 실패하면 None을 반환한다."""
    try:
        resp = requests.get(
            _DIRECTIONS_URL,
            headers=kakao_headers(),
            params={
                "origin": f"{OFFICE_LNG},{OFFICE_LAT}",
                "destination": f"{dest_lng},{dest_lat}",
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


def _call_toll_api(from_code: str, to_code: str) -> dict:
    """한국도로공사 영업소간 통행요금 조회 API(bhoinstIntoTollList) 실호출부."""
    resp = requests.get(
        _TOLL_API_URL,
        params={
            "key": os.environ["EX_CO_KR_API_KEY"],
            "type": "json",
            "dprtrTolofCd": from_code,
            "arrvTolofCd": to_code,
        },
        timeout=10,
    )
    resp.raise_for_status()
    item = resp.json()["list"][0]
    distance_km = (
        float(item["crgw2SumDstne"]) + float(item["crgw4SumDstne"]) + float(item["crgw6SumDstne"])
    )
    return {
        "toll": int(item["nrmlKnd1Amt"]),  # 1종(승용차) 통행료
        "distance_km": distance_km,
        # 영업소 구간(고속도로)만 포함해 실제보다 짧다 — price_time()에서 카카오
        # 길찾기 실측값이 있으면 이 값을 덮어쓴다.
        "duration_min": int(item["hourUntDrveHour"]) * 60 + int(item["mmUntDrveHour"]),
    }


def price_time(dest_lat: float, dest_lng: float, dest_name: str) -> str:
    """'추천 명소'의 좌표(Recommend_place가 반환한 lat/lng를 그대로 넘김) 기준
    통행료·거리·소요시간을 조회한다. 통행료는 1종(승용차) 기준이다.

    통행료·거리는 두 영업소 사이 고속도로 구간만 포함한다(연료비 계산용). 편도
    소요시간은 그와 별개로, 삼성SDS 본사에서 추천 명소까지 카카오모빌리티 길찾기로
    조회한 실제 도로 기준 값이다(다른 구간을 더하지 않은 문 앞~문 앞 소요시간).
    """
    dest_station = _nearest_station(dest_lat, dest_lng)
    try:
        result = _call_toll_api(_ORIGIN_STATION["영업소코드"], dest_station["영업소코드"])
    except Exception:
        return json.dumps({"error": "통행료 조회에 실패했습니다. 데이터 없음으로 처리합니다."}, ensure_ascii=False)

    real_duration = _office_to_dest_duration_min(dest_lat, dest_lng)
    if real_duration is not None:
        result["duration_min"] = real_duration
    result["duration_display"] = _format_duration(result["duration_min"])

    result["destination"] = dest_name
    result["origin_station"] = _ORIGIN_STATION["영업소명"]
    result["destination_station"] = dest_station["영업소명"]
    result["note"] = (
        "통행료·거리는 고속도로 영업소 구간만 포함한 값이고, 편도 소요시간은 "
        "삼성SDS 본사에서 추천 명소까지 실제 도로 기준(카카오모빌리티 길찾기) 값입니다."
    )
    return json.dumps(result, ensure_ascii=False)
