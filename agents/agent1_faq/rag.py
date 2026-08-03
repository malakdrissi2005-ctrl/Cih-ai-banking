"""Accès à la collection ChromaDB `faq_generale` — RAG public de l'Agent 1.

Voir `DocsContext/02_architecture_multi_agents.md` (§2.2) : cette collection
ne contient et ne contiendra jamais que du contenu FAQ **public**, jamais de
donnée personnelle ou transactionnelle.

Déviation documentée (voir CLAUDE.md, règle de contribution n°4) : plutôt que
la fonction d'embedding par défaut de ChromaDB (modèle `sentence-transformers`
téléchargé à la volée depuis Internet au premier appel), ce module utilise un
embedding "sac de mots haché" — déterministe, 100% local, sans aucune
dépendance réseau ni modèle externe. Ce choix est cohérent avec la stratégie
de confidentialité et d'indépendance réseau déjà retenue pour Mistral/Ollama
(`03_stack_technique.md`, §3.1). Il pourra être remplacé par un embedding
sémantique plus riche dans une phase ultérieure sans changer le contrat
d'ingestion (`upsert` par id stable) ni celui de recherche (`search_faq`).
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb import Settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

# Racine du dépôt (agents/agent1_faq/rag.py -> agents/agent1_faq -> agents -> racine).
# `CHROMA_PERSIST_DIR` (voir .env.example) est documenté comme un chemin relatif à
# la racine du monorepo (arborescence `03_stack_technique.md` §4.1, `chroma_db/`
# au même niveau que `backend/`) — jamais relatif au répertoire courant du
# processus, qui varie selon l'endroit d'où une commande est lancée.
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_FAQ", "faq_generale")


def _resolve_persist_dir(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return str(path)


DEFAULT_PERSIST_DIR = _resolve_persist_dir(os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"))

_VECTOR_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokenize(text: str) -> list[str]:
    cleaned = _strip_accents(text.lower())
    tokens = _TOKEN_RE.findall(cleaned)
    return tokens or ["__empty__"]


def _stable_hash(token: str) -> int:
    """Hash déterministe (indépendant du process et de PYTHONHASHSEED).

    Le `hash()` natif de Python est aléatoire d'un lancement à l'autre pour
    les chaînes de caractères : inutilisable ici, puisque l'ingestion (script
    CLI) et la recherche (API) tournent dans deux processus distincts et
    doivent produire strictement le même embedding pour un même texte.
    """
    import zlib

    return zlib.crc32(token.encode("utf-8"))


class HashingBagOfWordsEmbedding(EmbeddingFunction):
    """Embedding sac-de-mots haché, déterministe, sans dépendance réseau."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        return "hashing-bag-of-words"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashingBagOfWordsEmbedding":
        return HashingBagOfWordsEmbedding()

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - nom imposé par l'interface ChromaDB
        vectors: list[list[float]] = []
        for text in input:
            vector = [0.0] * _VECTOR_DIM
            for token in _tokenize(text):
                index = _stable_hash(token) % _VECTOR_DIM
                vector[index] += 1.0
            norm = sum(value * value for value in vector) ** 0.5
            if norm > 0:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        return vectors


def get_chroma_client(persist_dir: Optional[str] = None) -> Any:
    resolved = _resolve_persist_dir(persist_dir) if persist_dir else DEFAULT_PERSIST_DIR
    return chromadb.PersistentClient(
        path=resolved,
        settings=Settings(anonymized_telemetry=False),
    )


def get_faq_collection(
    persist_dir: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> Any:
    client = get_chroma_client(persist_dir)
    return client.get_or_create_collection(
        name=collection_name or DEFAULT_COLLECTION_NAME,
        embedding_function=HashingBagOfWordsEmbedding(),
        metadata={"hnsw:space": "cosine"},
    )


def search_faq(collection: Any, query: str, top_k: int = 1) -> Optional[dict]:
    """Retourne la meilleure correspondance FAQ, ou `None` si la collection est vide."""
    if collection.count() == 0:
        return None

    result = collection.query(query_texts=[query], n_results=min(top_k, collection.count()))
    ids = result.get("ids") or []
    if not ids or not ids[0]:
        return None

    metadata = result["metadatas"][0][0]
    distances = result.get("distances")
    return {
        "question": metadata.get("question"),
        "answer": metadata.get("answer"),
        "distance": distances[0][0] if distances else None,
    }


def search_faq_candidates(collection: Any, query: str, top_k: int = 5) -> list[dict]:
    """Retourne jusqu'à `top_k` correspondances FAQ, triées par pertinence
    (la plus proche en premier) — liste vide si la collection est vide.

    Contrairement à `search_faq` (top-1 uniquement, comportement historique
    inchangé, toujours utilisé quand le LLM Router est désactivé), permet une
    étape de reranking ultérieure (voir `llm_router.rerank_faq_candidates`)
    sur plusieurs candidats plutôt que de s'en remettre uniquement à la
    distance cosinus de l'embedding "sac de mots haché" — utile quand la
    question contient des fautes de frappe ou de la darija mal normalisée.
    """
    if collection.count() == 0:
        return []

    result = collection.query(query_texts=[query], n_results=min(top_k, collection.count()))
    ids = result.get("ids") or []
    if not ids or not ids[0]:
        return []

    metadatas = result["metadatas"][0]
    distances = (result.get("distances") or [[None] * len(metadatas)])[0]
    return [
        {"question": metadata.get("question"), "answer": metadata.get("answer"), "distance": distance}
        for metadata, distance in zip(metadatas, distances)
    ]
