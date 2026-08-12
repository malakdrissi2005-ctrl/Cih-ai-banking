"""Tests de `scripts/ingest_faq.py` : création de faq.json, idempotence, FAQ vide."""
import os
import sqlite3

import chromadb
from chromadb import Settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

import json

from agents.agent1_faq.rag import get_faq_collection
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


# ---------------------------------------------------------------------------
# Remplacement automatique d'une collection FAQ incompatible.
#
# NON-RÉGRESSION D'UNE PANNE RÉELLE : après le passage à
# `HashingBagOfWordsEmbedding` v2 (stemming + 1024 dimensions), une collection
# créée par la v1 (`hashing-bag-of-words`, 256 dimensions) ne pouvait plus être
# ouverte — y compris par `ingest_faq` lui-même, qui était pourtant LA commande
# censée réparer la situation. L'utilisateur se retrouvait sans issue autre que
# supprimer le dossier `chroma_db/` à la main.
# ---------------------------------------------------------------------------


class _LegacyEmbeddingV1(EmbeddingFunction):
    """Ancienne fonction d'embedding : nom v1, 256 dimensions."""

    @staticmethod
    def name() -> str:
        return "hashing-bag-of-words"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "_LegacyEmbeddingV1":
        return _LegacyEmbeddingV1()

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 — signature ChromaDB
        return [[0.0] * 255 + [1.0] for _ in input]


def _build_legacy_collection(persist_dir: str, name: str, documents: list[str]) -> None:
    client = chromadb.PersistentClient(path=persist_dir, settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection(
        name=name, embedding_function=_LegacyEmbeddingV1(), metadata={"hnsw:space": "cosine"}
    )
    collection.upsert(
        ids=[f"legacy-{index}" for index in range(len(documents))],
        documents=documents,
        metadatas=[{"question": doc, "answer": "ancienne réponse"} for doc in documents],
    )


def test_reingestion_replaces_an_incompatible_collection(faq_json_path, chroma_persist_dir):
    """`ingest_faq` doit réparer tout seul un index créé par l'ancien embedding."""
    _build_legacy_collection(chroma_persist_dir, "faq_legacy_rebuild", ["vieille entrée"])

    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps([{"id": "faq-1", "question": "Question ?", "answer": "Réponse."}]), encoding="utf-8"
    )

    stats = ingest_faq(
        faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_legacy_rebuild"
    )

    assert stats["rebuilt"] is True
    assert stats["collection_count"] == 1

    collection = get_faq_collection(persist_dir=chroma_persist_dir, collection_name="faq_legacy_rebuild")
    embeddings = collection.get(limit=1, include=["embeddings"])["embeddings"]
    assert len(embeddings[0]) == 1024  # et non plus 256


def test_rebuild_backs_up_the_previous_index(faq_json_path, chroma_persist_dir):
    """Une sauvegarde horodatée est créée AVANT toute suppression."""
    _build_legacy_collection(chroma_persist_dir, "faq_backup_test", ["vieille entrée"])

    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps([{"id": "faq-1", "question": "Question ?", "answer": "Réponse."}]), encoding="utf-8"
    )

    stats = ingest_faq(
        faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_backup_test"
    )

    backup = stats["backup_path"]
    assert backup is not None
    assert os.path.exists(backup)
    assert backup.endswith(".sqlite3")  # donc couvert par .gitignore
    # La sauvegarde est bien une base ChromaDB lisible, pas un fichier vide.
    with sqlite3.connect(backup) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "collections" in tables


def test_rebuild_never_touches_other_collections(faq_json_path, chroma_persist_dir):
    """SÉCURITÉ DES DONNÉES : seule la collection FAQ nommée est supprimée.

    Aucune autre collection du même magasin vectoriel ne doit disparaître —
    la suppression passe par `client.delete_collection(name)`, jamais par un
    effacement de dossier."""
    _build_legacy_collection(chroma_persist_dir, "faq_cible", ["vieille entrée FAQ"])
    _build_legacy_collection(chroma_persist_dir, "collection_voisine", ["à préserver"])

    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps([{"id": "faq-1", "question": "Question ?", "answer": "Réponse."}]), encoding="utf-8"
    )

    ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_cible")

    client = chromadb.PersistentClient(path=chroma_persist_dir, settings=Settings(anonymized_telemetry=False))
    noms = {collection.name for collection in client.list_collections()}
    assert "collection_voisine" in noms
    assert client.get_collection("collection_voisine").count() == 1


def test_a_compatible_collection_is_never_rebuilt(faq_json_path, chroma_persist_dir):
    """Contrepartie : un index sain ne doit jamais être supprimé ni sauvegardé
    inutilement — `rebuilt` reste `False` et l'ingestion suit son cours normal."""
    faq_json_path.parent.mkdir(parents=True, exist_ok=True)
    faq_json_path.write_text(
        json.dumps([{"id": "faq-1", "question": "Question ?", "answer": "Réponse."}]), encoding="utf-8"
    )

    first = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_sain")
    second = ingest_faq(faq_path=faq_json_path, persist_dir=chroma_persist_dir, collection_name="faq_sain")

    assert first["rebuilt"] is False
    assert second["rebuilt"] is False
    assert second["backup_path"] is None
    assert second["collection_count"] == 1
