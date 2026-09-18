# resilient_llm.py - ThrottlingException 발생 시 다른 Bedrock 모델로 자동 전환
"""
같은 모델에 그대로 재시도하면 같은 처리 한도(TPM/RPM)에 계속 부딪힌다.
서로 다른 모델은 별도의 한도를 쓰므로, 모델을 바꿔 가며 재시도하면 성공 확률이 올라간다.
(day7_practice/resilient_llm.py와 동일한 패턴을 그대로 재사용)
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from botocore.exceptions import ClientError
from langchain_aws import ChatBedrockConverse
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

# 사용 가능하다고 확인된 Bedrock 모델 목록. 맨 앞이 기본 모델이고,
# 그 뒤로는 ThrottlingException이 났을 때 순서대로 시도할 대체 모델이다.
FALLBACK_MODEL_IDS: list[str] = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
]


def is_throttling_error(exc: BaseException) -> bool:
    """botocore ThrottlingException(ClientError의 한 종류)인지 판정한다."""
    response = getattr(exc, "response", None)
    code = ""
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code", "")
    return code == "ThrottlingException" or type(exc).__name__ == "ThrottlingException"


class ResilientChatBedrockConverse(ChatBedrockConverse):
    """ChatBedrockConverse와 완전히 같게 쓰되, ThrottlingException이 나면
    FALLBACK_MODEL_IDS의 다음 모델로 자동 전환해 재시도한다.

    다른 종류의 예외(인증 실패, 스키마 오류 등)는 그대로 던진다 —
    한도 문제가 아닌 것까지 모델을 바꿔 가며 재시도하면 문제만 가린다.
    """

    def _candidate_model_ids(self) -> list[str]:
        return [self.model_id] + [m for m in FALLBACK_MODEL_IDS if m != self.model_id]

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_exc: BaseException | None = None
        for attempt, model_id in enumerate(self._candidate_model_ids()):
            candidate = self if model_id == self.model_id else self.model_copy(update={"model_id": model_id})
            try:
                return ChatBedrockConverse._generate(
                    candidate, messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except ClientError as exc:
                if not is_throttling_error(exc):
                    raise
                last_exc = exc
                time.sleep(min(2**attempt, 8) + random.random())
        assert last_exc is not None
        raise last_exc

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_exc: BaseException | None = None
        for attempt, model_id in enumerate(self._candidate_model_ids()):
            candidate = self if model_id == self.model_id else self.model_copy(update={"model_id": model_id})
            try:
                return await ChatBedrockConverse._agenerate(
                    candidate, messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except ClientError as exc:
                if not is_throttling_error(exc):
                    raise
                last_exc = exc
                await asyncio.sleep(min(2**attempt, 8) + random.random())
        assert last_exc is not None
        raise last_exc
