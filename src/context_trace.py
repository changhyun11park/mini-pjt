"""context_trace.py - 실행 메시지에서 POST /query 응답용 contexts/trace를 뽑는다."""
import json

from langchain_core.messages import AIMessage, ToolMessage

from masking import to_text as _as_text


def build_contexts(messages: list) -> list[dict]:
    """ToolMessage들의 원본 결과를 그대로 모은다 (raw 값 대조 채점용)."""
    contexts = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        text = _as_text(msg.content)
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed = text
        contexts.append({"tool": getattr(msg, "name", None), "result": parsed})
    return contexts


def build_trace(messages: list) -> list[dict]:
    """실행 순서대로 {seq, type, name, args/content}를 나열한다."""
    trace = []
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                trace.append({"seq": i, "type": "tool_call", "name": tc["name"], "args": tc.get("args", {})})
        elif isinstance(msg, ToolMessage):
            trace.append({"seq": i, "type": "tool_result", "name": getattr(msg, "name", None), "content": _as_text(msg.content)})
        elif isinstance(msg, AIMessage) and msg.content:
            trace.append({"seq": i, "type": "answer", "content": _as_text(msg.content)})
    return trace
