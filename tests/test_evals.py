from pathlib import Path

from airreview.evals import run_local_evals


def test_local_evals_pass_with_mock(tmp_path: Path) -> None:
    result = run_local_evals(tmp_path, mock=True)
    assert result["passed"] == result["total"]
    assert result["total"] >= 2
