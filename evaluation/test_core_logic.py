"""test_core_logic.py - 가장 최근 라운드(evaluation/results/round_NN/, run_eval.py가
저장한 실제 실행 결과)를 rules.py 규칙으로 채점하는 pytest 스위트.

이 파일은 라이브 API를 다시 호출하지 않는다 — 가장 최근에 `python evaluation/run_eval.py`로
저장해 둔 라운드만 검사한다. 새로 실행한 뒤 채점하려면:
    python evaluation/run_eval.py && pytest evaluation/test_core_logic.py -v
"""
import csv
import json
import os

import pytest

import rounds
import rules

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
_QUERIES_PATH = os.path.join(_EVAL_DIR, "test_queries.csv")


def _load_cases() -> list[dict]:
    with open(_QUERIES_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


CASES = _load_cases()
LATEST_ROUND_DIR = rounds.latest_round_dir()


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}_{c['category']}" for c in CASES])
def test_case_matches_core_logic(case: dict) -> None:
    if LATEST_ROUND_DIR is None:
        pytest.skip("라운드 결과 없음 — 먼저 python evaluation/run_eval.py를 실행하세요.")

    result_path = os.path.join(LATEST_ROUND_DIR, f"case_{int(case['id']):02d}.json")
    if not os.path.exists(result_path):
        pytest.skip(f"{result_path} 없음 — 먼저 python evaluation/run_eval.py를 실행하세요.")

    with open(result_path, encoding="utf-8") as f:
        saved = json.load(f)
    result = saved["result"]

    if result.get("answer") is None:
        pytest.fail(f"fast_path가 이 질문을 처리하지 못함: {result.get('error')}")

    checks = rules.check(case, result)
    failures = [reason for ok, reason in checks if not ok]
    assert not failures, "\n" + "\n".join(failures)
