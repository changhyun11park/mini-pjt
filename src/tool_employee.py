"""tool_employee.py - Search_Employee 도구: 이름/임직원ID로 가족 구성을 조회한다."""
import json
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_EMPLOYEES_PATH = os.path.join(_BASE_DIR, "..", "data", "employee.json")

with open(_EMPLOYEES_PATH, encoding="utf-8") as f:
    EMPLOYEES: list[dict] = json.load(f)

# 이름별 등록 인원 수 (동명이인 판정용). 임직원ID로 바로 조회해 단일 레코드가
# 확정되는 경우에도, 그 이름 자체가 동명이인인지는 프런트엔드가 알아야
# 화면에 "이름(사번)"으로 구분해 보여줄 수 있다 — 화면에 지금 같이 떠 있는
# 다른 행과 우연히 겹치는지가 아니라 실제 등록 데이터 기준으로 판정한다.
_NAME_COUNTS: dict[str, int] = {}
for _e in EMPLOYEES:
    _NAME_COUNTS[_e["name"]] = _NAME_COUNTS.get(_e["name"], 0) + 1


def search_employee(name_or_id: str) -> str:
    """이름 또는 임직원ID(SDS로 시작)로 임직원의 가족 구성을 조회한다.

    동명이인이 있으면 상세 정보 대신 후보 목록(ambiguous=true)을 반환하니,
    이 경우 지어내지 말고 임직원ID를 추가로 확인해야 한다. 임직원ID로 바로
    조회해 단일 레코드가 확정된 경우에도 name_has_duplicates로 그 이름이
    동명이인인지 함께 알려준다.
    """
    key = name_or_id.strip()
    if key.upper().startswith("SDS"):
        emp = next((e for e in EMPLOYEES if e["id"] == key.upper()), None)
        if emp is None:
            return json.dumps({"error": "등록되지 않은 임직원ID입니다."}, ensure_ascii=False)
        return json.dumps(
            {**emp, "name_has_duplicates": _NAME_COUNTS[emp["name"]] > 1}, ensure_ascii=False
        )

    matches = [e for e in EMPLOYEES if e["name"] == key]
    if not matches:
        return json.dumps({"error": f"'{key}' 임직원을 찾을 수 없습니다."}, ensure_ascii=False)
    if len(matches) > 1:
        candidates = [{"id": e["id"], "name": e["name"], "team": e["team"]} for e in matches]
        return json.dumps({"ambiguous": True, "candidates": candidates}, ensure_ascii=False)
    return json.dumps({**matches[0], "name_has_duplicates": False}, ensure_ascii=False)
