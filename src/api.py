"""api.py - FastAPI 서버: POST /query 로 받아 answer/contexts/trace 세 키로 돌려준다.

GET / 은 static/index.html(임직원 이름·지역명 입력 웹 클라이언트)을 그대로 서빙한다 —
이 페이지도 내부적으로는 POST /query를 호출할 뿐이라 제출 규약(주고받는 형식)은 그대로다.

POST /query는 세 단계로 처리한다(대기 시간 단축):
  1. fast_path.resolve()로 동명이인·미등록 임직원·지역 가드레일이면 Bedrock 없이
     즉시 답한다.
  2. 임직원 1명 + 유효한 지역이 확정되면(가장 흔한 경우) pipeline.run()이 나머지
     도구 호출 체인을 고정 순서로 실행하고 LLM은 마지막 문장 다듬기 1번만 부른다.
  3. 그 외(질문에서 이름·지역을 못 뽑는 자유 문장 등)만 전체 ReAct Agent(agent.py)로
     넘긴다.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

import pipeline
from agent import build_agent, get_text
from context_trace import build_contexts, build_trace
from fast_path import resolve

_agent = None
_llm = None
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_INDEX_HTML_PATH = os.path.join(_BASE_DIR, "static", "index.html")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _agent, _llm
    _agent, _llm = await build_agent()
    yield


app = FastAPI(lifespan=_lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_INDEX_HTML_PATH, encoding="utf-8") as f:
        return f.read()


class QueryRequest(BaseModel):
    question: str


@app.post("/query")
async def query(payload: QueryRequest):
    resolved = resolve(payload.question)

    if resolved["kind"] == "blocked":
        # 동명이인·미등록 임직원·지역 가드레일 — Bedrock 호출 없이 즉시 답한다.
        return resolved["response"]

    if resolved["kind"] == "ready":
        # 임직원 1명 + 유효한 지역 확정 — 나머지 도구 호출은 고정 순서로 실행하고
        # LLM은 마지막 문장 다듬기 1번만 부른다.
        return await pipeline.run(resolved["employee"], resolved["region"], _llm)

    # 이름·지역을 못 뽑는 자유 문장 등 — 전체 ReAct Agent가 처리한다.
    result = await _agent.ainvoke(
        {"messages": [HumanMessage(content=payload.question)]},
        config={"recursion_limit": 25},
    )
    messages = result["messages"]
    return {
        "answer": get_text(messages[-1]),
        "contexts": build_contexts(messages),
        "trace": build_trace(messages),
    }
