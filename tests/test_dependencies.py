from pathlib import Path

from airreview.dependencies import scan_dependency_context


def test_scan_package_json_dependencies(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"^19.0.0"},"devDependencies":{"typescript":"^5.7.0"}}',
        encoding="utf-8",
    )
    context = scan_dependency_context(tmp_path)
    assert "package.json" in context["package_manifests"]
    assert context["dependencies"]["react"] == "^19.0.0"
    assert context["dev_dependencies"]["typescript"] == "^5.7.0"
    assert context["notes"]
