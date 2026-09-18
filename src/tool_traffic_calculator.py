"""tool_traffic_calculator.py - Traffic_Calculator 도구: 왕복 교통비를 계산한다.

외부 API를 호출하지 않는 순수 계산 도구다.
"""
import json

FUEL_COST_PER_KM = 150  # 원/km 고정 단가


def traffic_calculator(toll: int, distance_km: float) -> str:
    """왕복 교통비 = (통행료 + 거리 × 유류비 단가) × 2 를 계산한다.

    거리는 편도 기준(Price_Time이 반환한 distance_km)을 그대로 넘긴다.
    """
    one_way = toll + distance_km * FUEL_COST_PER_KM
    round_trip = round(one_way * 2)
    return json.dumps({"round_trip_cost": round_trip}, ensure_ascii=False)
