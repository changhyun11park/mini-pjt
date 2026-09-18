"""run_eval.py - test_queries.csv의 16개 질문을 실제 fast_path/pipeline에 태워
결과(answer/contexts/trace)를 evaluation/results/round_NN/case_XX.json으로 저장하고,
그 라운드의 report.md까지 자동으로 만든다.

돌릴 때마다 새 round_NN/ 폴더가 생기므로(rounds.py) 이전 라운드 결과가 덮어써지지
않고 그대로 쌓인다 — 라운드 간 비교나 회귀 확인에 쓸 수 있다.

정상 케이스(목적지 확정)만 Bedrock을 1회씩 호출하고, 나머지 가드레일 케이스는
Bedrock 호출 없이 즉시 끝난다(api.py의 실제 처리 순서와 동일 — fast_path 먼저,
그 다음 필요할 때만 pipeline). 실시간 API 결과라 실행마다 값이 달라질 수 있으므로,
이 스크립트는 "실행 + 리포트 작성"만 담당하고, 규칙 판정 자체는 rules.py에 있다
(test_core_logic.py가 최신 라운드에 대해 같은 판정을 pytest로도 재확인한다).

사용법: mini-pjt 디렉터리에서 `python evaluation/run_eval.py` (또는 이 폴더 안에서
`python run_eval.py`) — src/의 .env(상위 디렉터리 탐색)와 로컬 모듈을 그대로 쓴다.
"""
import asyncio
import csv
import json
import os
import sys

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_EVAL_DIR, "..", "src")
sys.path.insert(0, _SRC_DIR)

from agent import make_llm  # noqa: E402
from fast_path import resolve  # noqa: E402
from pipeline import run as pipeline_run  # noqa: E402

import report  # noqa: E402
import rounds  # noqa: E402

_QUERIES_PATH = os.path.join(_EVAL_DIR, "test_queries.csv")


def _load_cases() -> list[dict]:
    with open(_QUERIES_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def _run_case(resolved: dict, llm) -> dict:
    if resolved["kind"] == "blocked":
        return resolved["response"]
    if resolved["kind"] == "ready":
        return await pipeline_run(resolved["employee"], resolved["region"], llm)
    return {
        "answer": None,
        "contexts": [],
        "trace": [],
        "error": (
            "fast_path가 이름/지역을 뽑지 못했습니다(unresolved) — "
            "질문이 '{이름}님 {지역} 여행 추천해줘' 형식인지 확인하세요."
        ),
    }


async def main() -> None:
    round_dir = rounds.next_round_dir()
    round_name = os.path.basename(round_dir)
    cases = _load_cases()
    llm = None  # 정상 케이스를 처음 만났을 때만 만든다(가드레일 케이스만 있으면 Bedrock 미호출)

    print(f"=== {round_name} 시작 ===", flush=True)
    for case in cases:
        resolved = resolve(case["question"])  # 케이스당 한 번만 판정(region 검증 API 중복 호출 방지)
        if resolved["kind"] == "ready" and llm is None:
            llm = make_llm()

        print(f"[{case['id']}] {case['category']} :: {case['question']}", flush=True)
        result = await _run_case(resolved, llm)

        out_path = os.path.join(round_dir, f"case_{int(case['id']):02d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"case": case, "result": result}, f, ensure_ascii=False, indent=2)

        preview = (result.get("answer") or "")[:80].replace("\n", " ")
        print(f"    -> {preview}...", flush=True)

    pass_count, total = report.generate(round_dir)
    print(f"=== {round_name} 완료: {pass_count}/{total} PASS ===", flush=True)
    print(f"리포트: {os.path.join(round_dir, 'report.md')}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
