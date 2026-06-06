from pathlib import Path
import json

from airreview.evals import run_local_evals


def test_local_evals_pass_with_mock(tmp_path: Path) -> None:
    result = run_local_evals(tmp_path, mock=True)
    assert result["passed"] == result["total"]
    assert result["total"] >= 2


def test_foundry_eval_datasets_are_json_objects() -> None:
    root = Path(__file__).resolve().parents[1] / "evals"
    datasets = sorted(root.glob("airreview_*.json"))
    assert datasets
    for path in datasets:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload["name"], str)
        assert payload["evaluators"]
        assert payload["data"]
        assert all("query" in row for row in payload["data"])
