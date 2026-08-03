"""Tests de `scripts/ingest_faq.py` : création de faq.json, idempotence, FAQ vide."""
import json

from scripts.ingest_faq import FaqValidationError, ensure_faq_file, ingest_faq


def test_faq_file_created_with_empty_array_if_missing(faq_json_path):
    assert not faq_json_path.exists()
    ensure_faq_file(faq_json_path)
    assert faq_json_path.exists()
    assert json.loads(faq_json_path.read_text(encoding="utf-8")) == []


def test_ensure_faq_file_does_not_overwrite_existing_content(faq_json_path):
    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(json.dumps([{"question": "Q", "answer": "A"}]), encoding="utf-8")

    ensure_faq_file(faq_json_path)

    assert json.loads(faq_json_path.read_text(encoding="utf-8")) == [{"question": "Q", "answer": "A"}]


def test_empty_faq_ingestion_does_not_error(faq_json_path, chroma_persist_dir):
    ensure_faq_file(faq_json_path)

    stats = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_empty")

    assert stats["total_entries"] == 0
    assert stats["collection_count"] == 0


def test_ingestion_populates_collection_without_duplicates_on_rerun(faq_json_path, chroma_persist_dir):
    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps(
            [
                {"question": "Quels documents pour ouvrir un compte ?", "answer": "CIN + justificatif de domicile."},
                {"question": "Quels sont les frais de tenue de compte ?", "answer": "Gratuit pour les moins de 26 ans."},
            ]
        ),
        encoding="utf-8",
    )

    stats1 = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_dup")
    assert stats1["collection_count"] == 2

    stats2 = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_dup")
    assert stats2["collection_count"] == 2  # pas de doublon après ré-ingestion


def test_reingestion_removes_stale_entries(faq_json_path, chroma_persist_dir):
    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps(
            [
                {"id": "faq-a", "question": "A ?", "answer": "réponse A"},
                {"id": "faq-b", "question": "B ?", "answer": "réponse B"},
            ]
        ),
        encoding="utf-8",
    )
    ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_stale")

    faq_json_path.write_text(
        json.dumps([{"id": "faq-a", "question": "A ?", "answer": "réponse A"}]),
        encoding="utf-8",
    )
    stats = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_stale")

    assert stats["collection_count"] == 1
    assert stats["removed"] == 1


def test_invalid_entry_raises_clear_error(faq_json_path, chroma_persist_dir):
    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(json.dumps([{"question": "Sans réponse ?"}]), encoding="utf-8")

    try:
        ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_test_invalid")
        assert False, "une FaqValidationError était attendue"
    except FaqValidationError as exc:
        assert "answer" in str(exc)
