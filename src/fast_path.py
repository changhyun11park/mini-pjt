"""fast_path.py - 질문 문장에서 이름·지역을 뽑아 이번 요청을 어떻게 처리할지 한 번에
판정한다.

질문 문장에서 "{이름 또는 사번}님"과 "{지역}"을 뽑아 순서대로 확인한다:
  1. search_employee 결과가 동명이인(ambiguous)이거나 등록되지 않은 임직원(error)이면
     "blocked" — Bedrock 호출 없이 그 자리에서 완성한 답을 즉시 돌려준다.
  2. 임직원이 단일 특정되면, 이어서 validate_region으로 지역만 확인한다(실제 명소
     검색인 recommend_place 전체를 다시 도는 게 아니라 지역 유효성만 가볍게 확인) —
     북한·해외·존재하지 않는 지역이면 마찬가지로 "blocked".
  3. 임직원 1명 + 유효한 지역이 모두 확정되면 "ready" — 이후 단계(recommend_place ~
     traffic_calculator)는 pipeline.py가 고정 순서로 실행하고 LLM은 마지막 답변
     문장을 다듬는 데만 한 번 쓰인다.
  4. 이름·지역을 못 뽑으면(자유 문장 질문, 지역 미입력 등) "unresolved" — 이 경우는
     여전히 전체 ReAct Agent(agent.py)가 처리해야 한다.
"""
import json
import re

from region_validator import validate_region
from tool_employee import search_employee

_NAME_PATTERN = re.compile(r"^\s*(\S+?)\s*님")
_REGION_PATTERN = re.compile(r"님\s*(.+?)\s*여행")


def _extract_name(question: str) -> str | None:
    """질문 맨 앞의 "{이름 또는 사번}님" 패턴에서 이름/사번만 뽑는다.

    웹 클라이언트가 항상 "{이름}님 {지역} 여행 추천해줘" 형태로 질문을 만들기
    때문에 이 패턴이면 충분하다. 못 뽑으면 None을 반환한다.
    """
    m = _NAME_PATTERN.match(question)
    return m.group(1) if m else None


def _extract_region(question: str) -> str | None:
    """"{이름}님"과 "여행" 사이의 지역명만 뽑는다. 못 뽑으면 None."""
    m = _REGION_PATTERN.search(question)
    return m.group(1) if m else None


def _blocked_employee_response(name_or_id: str, emp_raw: str, emp_data: dict) -> dict:
    if emp_data.get("ambiguous"):
        lines = "\n".join(
            f"- {c['name']} · {c['team']} ({c['id']})" for c in emp_data["candidates"]
        )
        answer = (
            f"{name_or_id}님이 동명이인으로 여러 분 계십니다. "
            f"아래에서 대상자를 확인해 주세요.\n\n{lines}"
        )
    else:
        answer = emp_data["error"]

    return {
        "answer": answer,
        "contexts": [{"tool": "search_employee", "result": emp_data}],
        "trace": [
            {"seq": 1, "type": "tool_call", "name": "search_employee", "args": {"name_or_id": name_or_id}},
            {"seq": 2, "type": "tool_result", "name": "search_employee", "content": emp_raw},
            {"seq": 3, "type": "answer", "content": answer},
        ],
    }


def _blocked_region_response(name_or_id: str, emp_raw: str, emp_data: dict, region: str, invalid: dict) -> dict:
    invalid_raw = json.dumps(invalid, ensure_ascii=False)
    return {
        "answer": invalid["message"],
        "contexts": [
            {"tool": "search_employee", "result": emp_data},
            {"tool": "recommend_place", "result": invalid},
        ],
        "trace": [
            {"seq": 1, "type": "tool_call", "name": "search_employee", "args": {"name_or_id": name_or_id}},
            {"seq": 2, "type": "tool_result", "name": "search_employee", "content": emp_raw},
            {"seq": 3, "type": "tool_call", "name": "recommend_place", "args": {"region": region, "family": emp_data.get("family", [])}},
            {"seq": 4, "type": "tool_result", "name": "recommend_place", "content": invalid_raw},
            {"seq": 5, "type": "answer", "content": invalid["message"]},
        ],
    }


def resolve(question: str) -> dict:
    """질문 하나를 한 번만 판정해 다음 중 하나의 모양으로 반환한다.

    {"kind": "blocked", "response": {...}}              동명이인/미등록/지역가드레일
    {"kind": "ready", "employee": {...}, "region": str}  임직원 1명 + 유효 지역 확정
    {"kind": "unresolved"}                               이름/지역을 못 뽑음
    """
    name_or_id = _extract_name(question)
    if not name_or_id:
        return {"kind": "unresolved"}

    emp_raw = search_employee(name_or_id)
    emp_data = json.loads(emp_raw)

    if emp_data.get("ambiguous") or emp_data.get("error"):
        return {"kind": "blocked", "response": _blocked_employee_response(name_or_id, emp_raw, emp_data)}

    region = _extract_region(question)
    if not region:
        return {"kind": "unresolved"}

    invalid = validate_region(region)
    if invalid is not None:
        return {"kind": "blocked", "response": _blocked_region_response(name_or_id, emp_raw, emp_data, region, invalid)}

    return {"kind": "ready", "employee": emp_data, "region": region}
