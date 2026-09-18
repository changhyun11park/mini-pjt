"""rounds.py - evaluation/results/ 밑에 실행마다 round_NN/ 폴더를 따로 두어,
run_eval.py를 다시 돌려도 이전 라운드 결과·리포트가 덮어써지지 않고 쌓이게 한다.
"""
import os
import re

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

_ROUND_RE = re.compile(r"round_(\d+)")


def _round_dirs() -> list[str]:
    if not os.path.isdir(RESULTS_DIR):
        return []
    names = [d for d in os.listdir(RESULTS_DIR) if _ROUND_RE.fullmatch(d)]
    return sorted(names, key=lambda d: int(_ROUND_RE.fullmatch(d).group(1)))


def next_round_dir() -> str:
    """새 라운드 폴더를 만들고 경로를 반환한다(번호는 기존 라운드 다음 번호)."""
    dirs = _round_dirs()
    n = int(_ROUND_RE.fullmatch(dirs[-1]).group(1)) + 1 if dirs else 1
    path = os.path.join(RESULTS_DIR, f"round_{n:02d}")
    os.makedirs(path, exist_ok=True)
    return path


def latest_round_dir() -> str | None:
    """가장 최근 라운드 폴더 경로. 라운드가 하나도 없으면 None."""
    dirs = _round_dirs()
    return os.path.join(RESULTS_DIR, dirs[-1]) if dirs else None
