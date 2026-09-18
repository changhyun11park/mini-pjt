"""link_section.py - LLM이 쓴 답변을 최종 형식으로 정리하는 후처리 모음: 답변 제목
(소제목·굵은 이름 라벨)에만 정확히 마크다운 링크를 걸고, 그 외 자리(인사말·설명
문단)나 표 뒤에 LLM이 스스로 남긴 링크·잔여 내용은 방어적으로 정리한다.

recommend_place·nearby_restaurant 결과(원본 dict)의 place_url(카카오 로컬 API가
실제로 제공하는 필드)만 그대로 쓴다 — 직접 지어내지 않는다. masking이 끝난 텍스트에
대해 코드에서 마지막으로 치환하므로(LLM이 URL을 옮겨 적다 실수할 일이 없다).
"""
import re

_MD_LINK_RE = re.compile(r"\[([^\[\]]+)\]\(https?://[^\s)]*\)")
_BARE_URL_RE = re.compile(r"https?://\S+")
_TABLE_ROW_RE = re.compile(r"^\|.*\|[ \t]*$", re.MULTILINE)


def strip_markdown_links(text: str) -> str:
    """LLM이 스스로 마크다운 링크·URL을 썼다면 평문으로 되돌린다 — 실제 링크는
    이후 linkify_places가 정해진 자리(소제목·굵은 라벨)에만 코드로 정확하게 붙인다."""
    text = _MD_LINK_RE.sub(r"\1", text)
    return _BARE_URL_RE.sub("", text)


def truncate_after_table(text: str) -> str:
    """참고 자료 표 뒤에 LLM이 덧붙인 내용이 있으면 표의 마지막 행에서 잘라낸다
    (프롬프트의 "표 뒤에는 아무것도 덧붙이지 않는다" 지침의 코드 백스톱)."""
    rows = list(_TABLE_ROW_RE.finditer(text))
    return text[: rows[-1].end()] if rows else text


def linkify_places(text: str, place: dict | None, restaurant: dict | None) -> str:
    """place(recommend_place 결과)·restaurant(nearby_restaurant 결과)에서
    place_url이 있는 항목의 이름을 '[이름](url)' 마크다운 링크로 바꾼다.

    이름이 실제로 나오는 두 자리 중 하나에만 정확히 링크를 건다 — 소제목 자리
    ("### ...: 이름" 줄 끝)를 먼저 찾고, 없으면 굵은 라벨 자리("**이름**")를
    찾는다. 인사말이나 설명 문단에 같은 이름이 먼저 나와도 텍스트 전체에서 처음
    등장하는 자리를 잡는 것이 아니므로 거기에는 링크가 걸리지 않는다.
    """
    entries: list[tuple[str, str]] = []

    top = place.get("추천_명소") if place else None
    if top and top.get("url"):
        entries.append((top["name"], top["url"]))

    for n in (place.get("그_외_가볼만한_곳") or []) if place else []:
        if n.get("url"):
            entries.append((n["name"], n["url"]))

    r = restaurant.get("추천_맛집") if restaurant else None
    if r and r.get("url"):
        entries.append((r["name"], r["url"]))

    # 긴 이름부터 치환해, 짧은 이름이 다른 긴 이름의 부분 문자열인 경우의 충돌을 피한다.
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    for name, url in entries:
        esc = re.escape(name)
        link = f"[{name}]({url})"
        text, hit = re.subn(
            rf"(?m)^(###[^\n]*:[ \t]*){esc}[ \t]*$",
            lambda m: m.group(1) + link,
            text,
            count=1,
        )
        if not hit:
            text = re.sub(rf"\*\*{esc}\*\*", lambda m: f"**{link}**", text, count=1)
    return text
