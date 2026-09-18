"""mcp_server.py - 주말 여행지 추천 Agent 도구 5개를 MCP 서버로 노출한다 (fastmcp).

노출하는 도구:
  - search_employee(name_or_id)                 임직원 가족 구성 조회
  - recommend_place(region, family)             지역+가족 구성 기반 명소 추천
  - price_time(dest_lat, dest_lng, dest_name)   통행료·거리·소요시간 조회
  - traffic_calculator(toll, distance_km)       왕복 교통비 계산
  - nearby_restaurant(lat, lng)                 추천 명소 주변 맛집 조회

실행: python mcp_server.py (stdio 모드로 대기)
"""
from fastmcp import FastMCP

from tool_employee import search_employee as _search_employee
from tool_place import recommend_place as _recommend_place
from tool_price_time import price_time as _price_time
from tool_restaurant import nearby_restaurant as _nearby_restaurant
from tool_traffic_calculator import traffic_calculator as _traffic_calculator

mcp = FastMCP("weekend-trip-agent")


@mcp.tool()
def search_employee(name_or_id: str) -> str:
    """이름 또는 임직원ID(SDS로 시작)로 임직원의 가족 구성을 조회한다.

    동명이인이 있으면 상세 정보 대신 후보 목록(ambiguous=true)을 반환하니,
    이 경우 지어내지 말고 담당자에게 임직원ID를 추가로 확인해야 한다.

    Args:
        name_or_id: 임직원 이름 또는 임직원ID (예: 'SDS10482')
    """
    return _search_employee(name_or_id)


@mcp.tool()
def recommend_place(region: str, family: list[dict]) -> str:
    """담당자가 입력한 지역과 가족 구성으로, 그 지역의 명소 중 최근 언급이 많은 곳을 검색한다.

    지역 없이는 호출하지 않는다 — 지역이 없으면 이 도구를 부르기 전에
    담당자에게 어느 지역으로 찾을지 먼저 물어봐야 한다.

    결과에 invalid_region:true가 있으면 북한 지역/해외 지역/존재하지 않는
    지역명 중 하나다. reason과 message를 확인해 message를 그대로 전달하고
    다른 지역명을 다시 물어봐야 한다(이후 단계로 진행하지 않는다).

    Args:
        region: 정확한 목적지 또는 "강원도"처럼 넓은 지역
        family: search_employee가 반환한 family 리스트를 그대로 전달 (이름/관계/나이)
    """
    return _recommend_place(region, family)


@mcp.tool()
def price_time(dest_lat: float, dest_lng: float, dest_name: str) -> str:
    """'추천 명소' 기준 통행료·거리·소요시간을 조회한다. 1종(승용차) 기준이다.

    recommend_place가 반환한 추천 명소의 lat/lng를 그대로 인자로 넘겨서 호출한다.

    Args:
        dest_lat: 추천 명소의 위도 (recommend_place 결과의 lat)
        dest_lng: 추천 명소의 경도 (recommend_place 결과의 lng)
        dest_name: 추천 명소 이름
    """
    return _price_time(dest_lat, dest_lng, dest_name)


@mcp.tool()
def nearby_restaurant(lat: float, lng: float) -> str:
    """'추천 명소' 주변(반경 1.5km) 맛집을 찾는다. 평점이 아니라 최근 블로그
    언급이 가장 많은 곳 하나를 추천한다.

    recommend_place가 반환한 추천 명소의 lat/lng를 그대로 인자로 넘겨서 호출한다.

    Args:
        lat: 추천 명소의 위도 (recommend_place 결과의 lat)
        lng: 추천 명소의 경도 (recommend_place 결과의 lng)
    """
    return _nearby_restaurant(lat, lng)


@mcp.tool()
def traffic_calculator(toll: int, distance_km: float) -> str:
    """왕복 교통비 = (통행료 + 거리 × 유류비 단가) × 2 를 계산한다.

    price_time이 반환한 toll, distance_km를 그대로 인자로 넘겨서 호출한다.

    Args:
        toll: price_time이 반환한 통행료
        distance_km: price_time이 반환한 거리(km, 편도)
    """
    return _traffic_calculator(toll, distance_km)


if __name__ == "__main__":
    mcp.run()  # stdio 모드로 실행
