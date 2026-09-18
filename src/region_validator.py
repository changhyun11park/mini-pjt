"""region_validator.py - 지역 입력값 검증: 북한/해외/존재하지 않는 지역을 미리 걸러낸다.

이 Agent는 국내 고속도로 통행료 API로 이동 비용을 계산하는 구조라, 대한민국 국민이
갈 수 없는 지역이나 자동차로 주말에 다녀오기 힘든 해외 지역은 애초에 다루지 않는다.
"""
import requests

from kakao_client import kakao_headers

_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 자주 나올 법한 북한 지역명 (완전한 목록은 아니지만 실습 프로젝트 범위에서는 충분하다)
_NORTH_KOREA_KEYWORDS = [
    "평양", "개성", "원산", "함흥", "청진", "신의주", "남포", "라선", "나선",
    "강계", "해주", "사리원", "만포", "혜산", "김책", "북한",
    "조선민주주의인민공화국",
]

# 자주 나올 법한 해외 국가·도시명 (편도 10시간 이상 걸리는 곳의 예시로, 완전한 목록은 아니다)
_OVERSEAS_KEYWORDS = [
    "미국", "뉴욕", "로스앤젤레스", "엘에이", "워싱턴", "시카고", "하와이",
    "유럽", "영국", "런던", "프랑스", "파리", "독일", "베를린",
    "이탈리아", "로마", "스페인", "바르셀로나", "네덜란드", "스위스",
    "캐나다", "호주", "시드니", "브라질", "러시아",
    "일본", "도쿄", "오사카", "중국", "베이징", "상하이",
    "해외", "외국",
]


def _region_exists(region: str) -> bool:
    """카카오 로컬 API로 실제 존재하는 국내 지역/장소인지 확인한다.

    행정 주소 검색(local/search/address.json)만 쓰면 '경포대'·'해운대'처럼
    정식 행정주소가 아닌 랜드마크·명소 이름이 전부 0건으로 나와 실존하는
    지역까지 '존재하지 않음'으로 잘못 판정한다(실측 확인). 명소·지명을 함께
    찾는 키워드(장소) 검색을 대신 쓴다.
    """
    resp = requests.get(
        _KEYWORD_URL,
        headers=kakao_headers(),
        params={"query": region, "size": 1},
        timeout=10,
    )
    resp.raise_for_status()
    return bool(resp.json().get("documents"))


def validate_region(region: str) -> dict | None:
    """지역명이 여행 가능한 국내 지역인지 확인한다. 문제없으면 None을 반환한다.

    북한 지역 → 여행 불가 안내, 해외 지역 → 거리가 너무 멀다는 안내,
    실존하지 않는 지역명 → 지역명 재확인 요청, 순서로 판정한다.
    """
    if any(kw in region for kw in _NORTH_KOREA_KEYWORDS):
        return {
            "invalid_region": True,
            "reason": "north_korea",
            "message": "해당 지역은 여행이 불가합니다. 국내 다른 지역으로 다시 알려주시겠어요?",
        }
    if any(kw in region for kw in _OVERSEAS_KEYWORDS):
        return {
            "invalid_region": True,
            "reason": "too_far",
            "message": (
                "거리가 멀어 주말 동안 다녀오시기 어려울 수 있어요. "
                "국내 여행지로 선택해보시는 건 어떨까요?"
            ),
        }
    if not _region_exists(region):
        return {
            "invalid_region": True,
            "reason": "not_found",
            "message": "입력하신 지역명을 찾을 수 없습니다. 지역명을 다시 확인해 주시겠어요?",
        }
    return None
