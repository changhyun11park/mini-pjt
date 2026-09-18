"""masking.py - 출력 가드레일: 최종 답변에서 가족 구성원 이름·나이를 마스킹한다.

임직원 본인 이름은 그대로 두고, 가족 구성원 개별 이름·나이만 지운다
(SERVICE.md 4번 가드레일).
"""
import json
import re


def to_text(content) -> str:
    """ToolMessage.content를 문자열로 정규화한다.

    MCP로 노출된 도구의 결과는 순수 문자열이 아니라
    [{"type": "text", "text": "..."}] 형태의 블록 리스트로 온다.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def collect_family_members(messages: list) -> list[dict]:
    """대화 메시지 중 search_employee 결과(ToolMessage)에서 family 리스트를 모은다."""
    members: list[dict] = []
    for msg in messages:
        text = to_text(getattr(msg, "content", None))
        if not text:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("family"), list):
            members.extend(data["family"])
    return members


def _mask_name(name: str) -> str:
    """성만 남기고 나머지는 '*'로 가린다 (예: '박서현' -> '박**')."""
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def mask_family_info(text: str, family_members: list[dict]) -> str:
    """가족 구성원 이름은 '성+**'로, 나이는 '{나이}세/살' 표기를 답변 텍스트에서 지운다."""
    masked = text
    for member in family_members:
        name = member.get("name")
        age = member.get("age")
        if name:
            masked = masked.replace(name, _mask_name(name))
        if age is not None:
            masked = re.sub(rf"{age}\s*(세|살)", "", masked)
    masked = re.sub(r"\(\s*\)", "", masked)
    return masked
