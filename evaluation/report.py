"""report.py - 한 라운드(evaluation/results/round_NN/)의 case_XX.json들을 사람이
읽기 좋은 round_NN/report.md로 모아 준다.

자동 채점(rules.py)은 공식·마스킹·형식처럼 기계적으로 판정 가능한 부분만 다루므로,
추천 사유 문장이 매력적인지·톤이 자연스러운지 같은 건 이 리포트를 사람이 직접 읽고
각 케이스 밑의 "피드백" 줄에 적어 판단한다. 그 판단이 이후 모범 답안 기준이 된다.

run_eval.py가 매 라운드 끝에 이 파일의 generate()를 자동으로 호출하므로 보통 따로
실행할 필요는 없다. 특정 라운드를 다시 렌더링하려면:
    python evaluation/report.py [round_NN]   (생략 시 최신 라운드)
"""
import glob
import json
import os
import re
import sys

import rounds
import rules


def _load_round_cases(round_dir: str) -> list[dict]:
    """round_dir 안의 case_XX.json을 id 순으로 읽어 [{"case":..., "result":...}, ...]로 반환."""
    paths = sorted(
        glob.glob(os.path.join(round_dir, "case_*.json")),
        key=lambda p: int(re.search(r"case_(\d+)\.json", p).group(1)),
    )
    loaded = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            loaded.append(json.load(f))
    return loaded


def generate(round_dir: str) -> tuple[int, int]:
    """round_dir/report.md를 작성하고 (pass_count, total)을 반환한다."""
    lines = ["# 평가 리포트", "", f"라운드: {os.path.basename(round_dir)}", ""]
    pass_count = 0
    total = 0

    for entry in _load_round_cases(round_dir):
        case, result = entry["case"], entry["result"]
        total += 1
        lines.append(f"## [{case['id']}] {case['category']}")
        lines.append("")
        lines.append(f"- 질문: `{case['question']}`")
        lines.append("")

        answer = result.get("answer")
        if answer is None:
            lines.append(f"- ⚠️ 처리 실패: {result.get('error')}")
            lines.append("")
            continue

        checks = rules.check(case, result)
        failures = [reason for ok, reason in checks if not ok]
        if failures:
            lines.append(f"- 자동 채점: ❌ FAIL ({len(failures)}건)")
            for reason in failures:
                lines.append(f"  - {reason}")
        else:
            lines.append(f"- 자동 채점: ✅ PASS ({len(checks)}개 항목)")
            pass_count += 1
        lines.append("")

        lines.append("- 답변:")
        lines.append("  ```")
        for line in answer.splitlines():
            lines.append(f"  {line}")
        lines.append("  ```")
        lines.append("- 사람 피드백(추천 사유·톤 등 자동 채점 밖의 판단): ")
        lines.append("")

    lines.insert(3, f"자동 채점 요약: {pass_count}/{total} PASS (16건 중 14건 이상이면 SERVICE.md 기준 통과)")
    lines.insert(4, "")

    report_path = os.path.join(round_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return pass_count, total


def main() -> None:
    round_dir = (
        os.path.join(rounds.RESULTS_DIR, sys.argv[1]) if len(sys.argv) > 1 else rounds.latest_round_dir()
    )
    if round_dir is None or not os.path.isdir(round_dir):
        print("라운드 결과가 없습니다 — 먼저 python evaluation/run_eval.py를 실행하세요.")
        return
    pass_count, total = generate(round_dir)
    print(f"작성 완료: {os.path.join(round_dir, 'report.md')} ({pass_count}/{total} PASS)")


if __name__ == "__main__":
    main()
