"""Pipeline d'ingestion de `data/faq_docs/faq.json` dans ChromaDB.

Voir `DocsContext/03_stack_technique.md` (§6). Le fichier `faq.json` est
rempli manuellement par l'équipe projet — ce script ne génère et ne complète
**jamais** de question ou de réponse fictive : s'il est absent, il est créé
avec un tableau vide `[]`, jamais avec un exemple pré-rempli.

Réingestion sans doublon : chaque entrée est identifiée par un `id` stable
(fourni, ou dérivé par hachage de la question) et l'ingestion utilise
`upsert`. Les entrées présentes dans la collection mais disparues de
`faq.json` sont supprimées, pour que la collection reflète exactement l'état
courant du fichier source.

Utilisation en CLI :
    python scripts/ingest_faq.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

# Exécution directe en script (pas via `python -m`) : le répertoire ajouté
# automatiquement à sys.path est celui de ce fichier (scripts/), pas la
# racine du dépôt. On l'ajoute explicitement pour pouvoir importer
# `agents.agent1_faq.rag`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.agent1_faq.rag import get_faq_collection  # noqa: E402

DEFAULT_FAQ_PATH = _REPO_ROOT / "data" / "faq_docs" / "faq.json"


class FaqValidationError(ValueError):
    """Levée quand `faq.json` contient une entrée invalide ou n'est pas une liste JSON."""


def ensure_faq_file(faq_path: Path) -> None:
    """Crée `faq.json` avec `[]` s'il n'existe pas encore. Ne touche jamais à un fichier existant."""
    faq_path = Path(faq_path)
    if not faq_path.exists():
        faq_path.parent.mkdir(parents=True, exist_ok=True)
        faq_path.write_text("[]\n", encoding="utf-8")


def _stable_id(question: str) -> str:
    digest = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"faq-{digest}"


def load_faq_entries(faq_path: Path) -> list[dict]:
    """Lit et valide `faq.json`. Lève `FaqValidationError` sur toute entrée invalide."""
    faq_path = Path(faq_path)
    ensure_faq_file(faq_path)

    raw = faq_path.read_text(encoding="utf-8").strip() or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FaqValidationError(f"{faq_path} : JSON invalide ({exc}).") from exc

    if not isinstance(data, list):
        raise FaqValidationError(
            f"{faq_path} : le contenu doit être une liste JSON, reçu {type(data).__name__}."
        )

    entries: list[dict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise FaqValidationError(
                f"Entrée #{index} invalide : un objet JSON est attendu, reçu {type(item).__name__}."
            )

        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            raise FaqValidationError(f"Entrée #{index} invalide : champ 'question' manquant ou vide.")

        answer = item.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise FaqValidationError(f"Entrée #{index} invalide : champ 'answer' manquant ou vide.")

        entry_id = item.get("id") or _stable_id(question)
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise FaqValidationError(
                f"Entrée #{index} invalide : le champ 'id' doit être une chaîne non vide s'il est fourni."
            )
        if entry_id in seen_ids:
            raise FaqValidationError(f"Entrée #{index} invalide : id '{entry_id}' dupliqué dans {faq_path}.")
        seen_ids.add(entry_id)

        category = item.get("category")
        entries.append(
            {
                "id": entry_id,
                "question": question.strip(),
                "answer": answer.strip(),
                "category": category.strip() if isinstance(category, str) and category.strip() else "generale",
            }
        )

    return entries


def ingest_faq(
    faq_path: Optional[Path] = None,
    persist_dir: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> dict:
    """Ingère `faq.json` dans ChromaDB. Idempotent : ré-exécutable sans créer de doublon."""
    faq_path = Path(faq_path) if faq_path else DEFAULT_FAQ_PATH
    entries = load_faq_entries(faq_path)

    collection = get_faq_collection(persist_dir=persist_dir, collection_name=collection_name)

    existing_ids = set(collection.get(include=[])["ids"])
    current_ids = {entry["id"] for entry in entries}

    stale_ids = list(existing_ids - current_ids)
    if stale_ids:
        collection.delete(ids=stale_ids)

    if entries:
        collection.upsert(
            ids=[entry["id"] for entry in entries],
            documents=[entry["question"] for entry in entries],
            metadatas=[
                {"question": entry["question"], "answer": entry["answer"], "category": entry["category"]}
                for entry in entries
            ],
        )

    return {
        "faq_path": str(faq_path),
        "total_entries": len(entries),
        "added_or_updated": len(entries),
        "removed": len(stale_ids),
        "collection_count": collection.count(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faq-path", default=None, help="Chemin vers faq.json (défaut : data/faq_docs/faq.json)")
    parser.add_argument(
        "--persist-dir", default=None, help="Dossier de persistance ChromaDB (défaut : CHROMA_PERSIST_DIR ou ./chroma_db)"
    )
    parser.add_argument(
        "--collection-name",
        default=None,
        help="Nom de la collection ChromaDB (défaut : CHROMA_COLLECTION_FAQ ou faq_generale)",
    )
    args = parser.parse_args()

    faq_path = Path(args.faq_path) if args.faq_path else DEFAULT_FAQ_PATH

    try:
        stats = ingest_faq(faq_path=faq_path, persist_dir=args.persist_dir, collection_name=args.collection_name)
    except FaqValidationError as exc:
        print(f"Erreur de validation de faq.json : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"FAQ source                        : {stats['faq_path']}")
    print(f"Entrées dans faq.json              : {stats['total_entries']}")
    print(f"Ajoutées/mises à jour              : {stats['added_or_updated']}")
    print(f"Supprimées (obsolètes)             : {stats['removed']}")
    print(f"Total dans la collection ChromaDB  : {stats['collection_count']}")


if __name__ == "__main__":
    main()
