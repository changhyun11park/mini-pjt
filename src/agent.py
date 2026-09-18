"""agent.py - 주말 여행지 추천 Agent 메인 그래프.

단일 create_agent 하나로 구성한다 (멀티에이전트 아님). 도구 5개는 mcp_server.py가
MCP로 노출하며, 이 파일은 MultiServerMCPClient로 그 도구들을 가져와 연결한다.

이 create_agent 기반 ReAct 에이전트는 이제 "질문에서 이름·지역을 못 뽑는 자유 문장"
같은 예외적인 경우의 안전망으로만 쓰인다 — 이름·지역이 깔끔히 뽑히는 보통의 경우는
api.py가 fast_path.py(가드레일 즉답) → pipeline.py(도구 호출 체인 고정 + LLM 1회
호출) 순서로 먼저 처리해서 Bedrock 호출을 크게 줄인다. 그래도 이 파일까지 오면,
입력 쪽 가드레일(동명이인 재확인, 지역 미입력 재확인)은 별도 그래프 분기 없이,
도구가 구조화된 "부족함" 값을 반환하면 LLM이 자연스럽게 되묻는 create_agent의
기본 ReAct 루프로 처리한다. 출력 쪽 가드레일(가족 이름·나이 마스킹, 고정 안내 문구
부착)만 실제 AgentMiddleware.after_model 훅으로 구현한다.
"""
import json
import os
import sys

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from link_section import linkify_places, strip_markdown_links, truncate_after_table
from masking import collect_family_members, mask_family_info, to_text
from resilient_llm import ResilientChatBedrockConverse

# 최종 답변 맨 마지막에 항상 그대로 붙이는 고정 안내 문구 (LLM이 매번 다르게 쓰지 않도록
# 코드에서 고정한다). masking이 끝난 뒤에 붙기 때문에 raw HTML을 그대로 넣어도 마스킹
# 정규식에 걸리지 않는다 — 웹 클라이언트가 이 부분만 작은 글씨로 스타일링할 수 있도록
# answer-footnote 클래스와 <br>로 줄바꿈을 명시적으로 넣는다.
ANSWER_FOOTER = (
    "\n\n"
    '<div class="answer-footnote">'
    "※ 위 교통비는 고속도로 통행료와 유류비를 포함한 추정치 입니다.<br>"
    "※ 명소 추천 근거는 평점이 아니라 가족 구성 적합도와 최근 블로그 언급 빈도입니다."
    "</div>"
)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SYSTEM_PROMPT = (
    "너는 삼성SDS 인사팀 담당자를 돕는 주말 여행지 추천 Agent다.\n"
    "\n"
    "[도구 호출 순서]\n"
    "1. search_employee로 대상 임직원의 가족 구성을 조회한다.\n"
    "   - 결과에 ambiguous:true가 있으면 동명이인이다. 지어내지 말고 담당자에게\n"
    "     임직원ID를 추가로 물어봐라.\n"
    "2. 담당자가 지역(정확한 목적지 또는 '강원도' 같은 넓은 지역)을 말하지 않았다면,\n"
    "   recommend_place를 호출하지 말고 먼저 어느 지역으로 찾을지 물어봐라.\n"
    "   지역이 있으면 항상 recommend_place(region, family)를 호출한다. family는\n"
    "   search_employee가 반환한 family 리스트를 그대로 넘긴다. 북한·해외처럼\n"
    "   보이거나 실존하지 않을 것 같은 지역이어도 네가 스스로 판단해서 곧바로\n"
    "   답하지 말고, 반드시 이 도구를 호출해 invalid_region 여부를 확인한 뒤\n"
    "   그 결과에 따라 답한다.\n"
    "   - 결과에 invalid_region:true가 있으면 지어내지 말고 message를 그대로\n"
    "     전달한다(message 안에 재입력 요청까지 이미 포함돼 있으니 다른 말을\n"
    "     덧붙이지 않는다). 이 답변에는 인사말·가족 구성(배우자·자녀 등)\n"
    "     이야기·추천 사유를 전혀 넣지 않고 message만 그대로 짧게 답한다.\n"
    "     이 경우 이후 단계로 진행하지 않는다.\n"
    "3. recommend_place가 반환한 추천 명소의 lat/lng를 그대로 price_time과\n"
    "   nearby_restaurant에 각각 넘겨 호출한다.\n"
    "4. price_time이 반환한 toll, distance_km를 그대로 traffic_calculator에 넘겨\n"
    "   왕복 교통비를 계산한다.\n"
    "\n"
    "[답변 형식]\n"
    "대상 임직원 이름을 넣어 한 주간 고생했다는 인사로 시작한다. 인사말과 추천 사유의\n"
    "어투는 recommend_place가 반환한 keyword_used에 맞춰 다르게 쓴다:\n"
    "- '혼자 가기 좋은'(1인 가구)이면 가족을 전혀 언급하지 않는다. '가족과 함께' 대신\n"
    "  '혼자 여유롭게'처럼 표현하고, 추천 사유도 아이 동반·가족 나들이 같은 표현 없이\n"
    "  혼자서 즐기기 좋은 점(여유·힐링·자유로움 등)을 강조한다.\n"
    "- '커플 여행'(배우자만 있음)이면 '배우자님과 함께'를 언급하고, 추천 사유도 커플이\n"
    "  즐기기 좋은 점(분위기·함께 즐길 거리 등)을 강조한다.\n"
    "- '아이와 가볼만한'(미성년 자녀 있음)이면 가족 구성원(배우자님, 아드님·따님 등)과\n"
    "  함께를 언급하고, 추천 사유도 아이와 함께 즐기기 좋은 점을 강조한다.\n"
    "- '가족여행'(그 외, 성인 자녀만 있는 가족 등)이면 '가족과 함께'를 언급하고, 추천\n"
    "  사유도 가족 모두가 즐기기 좋은 점을 강조한다.\n"
    "이번 주말 추천 명소로 다녀올 것을 권유한다. 인사말 다음 줄에 추천 명소 이름을\n"
    "소제목으로 띄운다(예: '### 🏞️ 이번 주 추천: {명소명}'). 이모지는 인사말과 이\n"
    "소제목에 하나씩 정도만 자연스럽게 쓰고 과하게 넣지 않는다. 추천 사유는 위 어투\n"
    "기준에 맞춰 분위기·볼거리·함께 즐길 거리 등을 자연스럽고 가고 싶은 마음이 들도록\n"
    "표현하고, 블로그 언급 건수 같은 구체적인 숫자는 답변에 적지 않는다.\n"
    "추천 명소 설명 다음에는 recommend_place가 반환한 그_외_가볼만한_곳 목록으로 '이번\n"
    "주 추천'과 같은 수준(###)의 소제목을 하나 더 쓴다. 이모지는 하나 정도만 자연스럽게\n"
    "쓴다. 목록이 비어 있으면 이 섹션 전체를 쓰지 않는다. 후보가 1곳이면 '### 🧭 함께\n"
    "가볼 곳: {장소명}'처럼 이름을 소제목에 넣고, 그 아래에 함께 가볼 만한 이유를\n"
    "'이번 주 추천'처럼 문단으로 설명한다. 후보가 2곳이면 '### 🧭 함께 가볼 곳'이라는\n"
    "소제목만 쓰고, 그 아래에 각 후보를 '**{장소명}**: {함께 가볼 만한 이유}' 형태로\n"
    "이름과 설명을 콜론(:)으로 이어 한 줄씩 쓴다. 두 경우 모두 소요시간·거리 같은\n"
    "구체적인 숫자는 적지 않는다.\n"
    "그다음 같은 수준(###)으로 주변 맛집 섹션을 쓴다. nearby_restaurant가 반환한\n"
    "추천_맛집이 있으면 '### 🍽️ 주변 맛집: {맛집명}'처럼 이름을 소제목에 넣고, 그\n"
    "아래에 주소를 적는다. 결과가 없으면 '### 🍽️ 주변 맛집' 소제목만 쓰고 그 아래에\n"
    "'데이터 없음'이라고 적는다(이 소제목 자체는 생략하지 않는다).\n"
    "교통비·소요시간은 본문이 아니라 맨 마지막에 '### 📋 참고 자료'처럼 이모지를\n"
    "하나 곁들인 소제목 아래 마크다운 표(테이블)로 정리한다 — 표의 행은 반드시 이\n"
    "순서로, 이 두 행만 쓴다: 1) '왕복 교통비'(약 OO원) 2) '편도 소요시간'(price_time이\n"
    "반환한 duration_display 값을 그대로 적는다 — 분 단위로 직접 환산하지 않는다).\n"
    "주변 맛집은 표에 넣지 않는다.\n"
    "표를 쓰고 나면 답변을 그 자리에서 즉시 끝낸다. 표 다음 줄에 문장이든 인용구(>)든\n"
    "안내 문구든 그 어떤 내용도 절대 덧붙이지 않는다 — 추정치라는 점 등 안내 문구는\n"
    "시스템이 표 뒤에 자동으로 붙이므로, 비슷한 문구를 직접 쓰면 같은 내용이 중복된다.\n"
    "\n"
    "[반드시 지킬 것]\n"
    "- 표가 답변의 마지막 내용이다. 표 뒤에 추가 문장을 쓰지 않는다(시스템이 안내 문구를\n"
    "  자동으로 붙인다).\n"
    "- 명소·맛집 이름 옆에 마크다운 링크나 http(s) 주소를 직접 쓰지 않는다. 이름은\n"
    "  항상 평문으로만 쓴다 — 실제 링크는 답변이 완성된 뒤 시스템이 코드로 정확한\n"
    "  자리에 자동으로 붙인다.\n"
    "- 등록되지 않은 명소·임직원은 지어내지 않는다. 조회 결과가 없으면 '데이터 없음'을\n"
    "  그대로 안내한다.\n"
    "- 답변은 담당자가 지정한 대상 임직원 1인에 대해서만 작성한다.\n"
    "- 가족 구성원은 성이든 이름만이든 실제 이름으로 절대 부르지 않는다. 항상 관계로만\n"
    "  지칭한다(예: 배우자님, 아드님, 따님). 대상 임직원 본인 이름만 답변에 써도 된다.\n"
    "- 가족 구성원의 나이도 답변에 절대 언급하지 않는다. 숫자('6세')든 한글 숫자\n"
    "  ('여섯 살')든 나이를 알 수 있는 표현은 어떤 형태로도 쓰지 않는다.\n"
)


def _find_tool_json(messages, tool_name: str) -> dict | None:
    """messages에서 tool_name의 마지막 ToolMessage 결과를 dict로 파싱해 반환한다."""
    for msg in reversed(messages):
        if getattr(msg, "name", None) != tool_name:
            continue
        try:
            data = json.loads(to_text(msg.content))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _has_completed_recommendation(messages) -> bool:
    """traffic_calculator까지 실제로 성공했는지 확인한다 (되묻는 중간 답변에는
    비용 안내 문구를 붙이지 않기 위한 판정)."""
    for msg in messages:
        if getattr(msg, "name", None) != "traffic_calculator":
            continue
        try:
            data = json.loads(to_text(msg.content))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "round_trip_cost" in data:
            return True
    return False


class FinalizeAnswerMiddleware(AgentMiddleware):
    """출력 가드레일: 최종 답변에서 가족 구성원 이름·나이를 마스킹하고,
    고정 안내 문구(ANSWER_FOOTER)를 붙인다."""

    def after_model(self, state, runtime):
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or last.tool_calls or not last.content:
            return None
        text = to_text(last.content)
        if not text:
            return None
        text = truncate_after_table(text)

        family = collect_family_members(state["messages"])
        if family:
            text = mask_family_info(text, family)

        if _has_completed_recommendation(state["messages"]):
            place = _find_tool_json(state["messages"], "recommend_place")
            restaurant = _find_tool_json(state["messages"], "nearby_restaurant")
            text = strip_markdown_links(text)
            text = linkify_places(text, place, restaurant)
            text = text + ANSWER_FOOTER

        if text == last.content:
            return None
        return {"messages": [AIMessage(content=text, id=last.id)]}


def make_llm() -> ResilientChatBedrockConverse:
    # ThrottlingException(일일/분당 토큰 한도)이 나면 resilient_llm.FALLBACK_MODEL_IDS
    # 순서대로 다른 모델로 자동 전환해 재시도한다.
    return ResilientChatBedrockConverse(
        model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        region_name="us-east-1",
        temperature=0,
    )


async def build_agent(llm=None):
    """주말 여행지 추천 Agent와 그 llm을 함께 만든다(llm은 pipeline.py가 최종 답변
    문장을 다듬을 때도 그대로 재사용한다). llm을 주입하면 그 모델을 그대로 쓴다.

    반환값: (agent, llm)
    """
    if llm is None:
        llm = make_llm()

    client = MultiServerMCPClient(
        {
            "travel": {
                "command": sys.executable,
                "args": [os.path.join(BASE_DIR, "mcp_server.py")],
                "transport": "stdio",
            }
        }
    )
    tools = await client.get_tools()

    agent = create_agent(
        llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=[FinalizeAnswerMiddleware()],
    )
    return agent, llm


def get_text(message) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content
