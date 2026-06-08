from pathlib import Path

from airreview.knowledge import LocalKnowledgeProvider, sample_practice_chunks


def test_bootstrap_generates_local_knowledge(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    provider = LocalKnowledgeProvider(tmp_path)
    status = provider.bootstrap(force=True)
    assert status.exists
    assert status.scanned_files >= 1
    assert "Python" in status.languages
    assert (tmp_path / ".airreview" / "codebase_guidelines.md").exists()


def test_practice_sampling_groups_real_code_examples(tmp_path: Path) -> None:
    (tmp_path / "src" / "lib").mkdir(parents=True)
    (tmp_path / "src" / "services").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "lib" / "money.ts").write_text("export const addMoney = (a: number, b: number) => a + b;\n", encoding="utf-8")
    (tmp_path / "src" / "services" / "orders.ts").write_text("export async function loadOrders() { return []; }\n", encoding="utf-8")
    (tmp_path / "tests" / "orders.test.ts").write_text("import { describe, it } from 'vitest';\n", encoding="utf-8")

    chunks = sample_practice_chunks(tmp_path, ["src/services/orders.ts"], max_files=10, max_files_per_chunk=3)

    assert len(chunks) >= 2
    names = {chunk.name for chunk in chunks}
    assert "services-and-api" in names
    assert "tests" in names


def test_practice_profile_save_writes_profile_and_smell_proposal(tmp_path: Path) -> None:
    provider = LocalKnowledgeProvider(tmp_path)
    provider.bootstrap(force=True)
    profile = {
        "observed_practices": [{"practice": "Use shared helpers.", "confidence": "medium"}],
        "legacy_smells_to_ignore_in_reviews": [
            {
                "smell": "Legacy direct DOM query in old tests",
                "where_seen": "tests/legacy.test.ts",
                "ignore_rule": "Ignore only when not introduced or aggravated by the current branch.",
                "confidence": "medium",
            }
        ],
    }

    provider.save_practice_profile(profile, [], [])

    assert (tmp_path / ".airreview" / "practice_profile.json").exists()
    assert (tmp_path / ".airreview" / "generated" / "practice_profile.md").exists()
    assert (tmp_path / ".airreview" / "generated" / "known_smells.proposed.md").exists()
    assert "Legacy direct DOM query" not in (tmp_path / ".airreview" / "known_smells.md").read_text(encoding="utf-8")
