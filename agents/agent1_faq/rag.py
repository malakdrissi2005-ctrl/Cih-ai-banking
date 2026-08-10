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

# Dimension du vecteur d'embedding. Portée de 256 à 1024 : le corpus FAQ
# compte ~295 tokens uniques pour 256 cases, ce qui rendait les collisions
# inévitables (principe des tiroirs) — 68 % des tokens partageaient une case
# avec un autre mot, mesuré avant changement (ex. "compte" écrasé avec
# "facteur" et "propose"). À 1024, le taux de collision tombe à ~24 %.
#
# ATTENTION : toute modification de cette valeur rend les collections
# ChromaDB déjà persistées INUTILISABLES — il faut re-lancer
# `python scripts/ingest_faq.py`. Cette incompatibilité est détectée
# explicitement par `_assert_collection_dimension` plus bas, jamais laissée
# silencieuse.
_VECTOR_DIM = 1024
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ---------------------------------------------------------------------------
# Stemming léger français — appliqué DANS `_tokenize` ci-dessous (donc dans le
# pipeline d'embedding existant), jamais comme un système parallèle.
#
# Objectif : faire converger les variantes lexicales d'un même mot vers une
# racine commune, pour que "transactions" et "transaction", ou "consulter",
# "consulte" et "consultent", produisent le même vecteur.
#
# Ce n'est PAS un stemmer linguistique (type Snowball) : aucune dépendance,
# aucun téléchargement, quelques règles contrôlées seulement. La racine
# produite n'est pas nécessairement le singulier correct ("carte" -> "cart") :
# seule compte la CONVERGENCE des variantes, puisque la même transformation
# est appliquée au document et à la requête.
#
# Trois protections contre les faux positifs :
# 1. `_STEM_MIN_ROOT_LENGTH` : jamais de racine plus courte que 4 caractères,
#    ce qui protège naturellement les mots courts ("mois" -> "moi" refusé,
#    "pays" -> "pay" refusé, qui auraient fusionné avec "moi" et "payer").
# 2. `_STEM_INVARIANT_TOKENS` : mots fréquents en contexte bancaire terminés
#    par "s" au singulier, jamais découpés.
# 3. Un seul suffixe retiré par mot (jamais en cascade), et uniquement sur des
#    tokens purement alphabétiques (les montants/dates restent intacts).
_STEM_MIN_ROOT_LENGTH = 4

_STEM_INVARIANT_TOKENS = frozenset(
    {
        # Singuliers terminés par "s" (le retrait du "s" les dénaturerait).
        "frais", "temps", "cours", "corps", "univers", "divers",
        "acces", "succes", "processus", "virus", "bonus", "malus",
        # Mots-outils fréquents.
        "apres", "depuis", "jamais", "alors", "toujours", "plusieurs",
        # Termes bancaires à préserver tels quels.
        "interets", "especes",
    }
)

# Suffixes dérivationnels/verbaux, du plus long au plus court. Le pluriel est
# traité séparément (phase 1) pour garantir que singulier et pluriel
# convergent toujours vers la même racine.
_STEM_SUFFIXES = ("ation", "ement", "aient", "ent", "er", "e")


def _light_stem(token: str) -> str:
    """Réduit un token à une racine stable. Déterministe, sans dépendance.

    Deux phases : (1) retrait d'un "s" de pluriel, (2) retrait d'AU PLUS un
    suffixe dérivationnel. Cet ordre est ce qui garantit la convergence
    singulier/pluriel : "virements" -> "virement" -> "virem", et
    "virement" -> "virem".
    """
    if token in _STEM_INVARIANT_TOKENS or not token.isalpha():
        return token

    stem = token

    # Phase 1 — pluriel.
    if stem.endswith("s") and len(stem) - 1 >= _STEM_MIN_ROOT_LENGTH:
        stem = stem[:-1]
        if stem in _STEM_INVARIANT_TOKENS:
            return stem

    # Phase 2 — un seul suffixe dérivationnel/verbal.
    for suffix in _STEM_SUFFIXES:
        if stem.endswith(suffix) and len(stem) - len(suffix) >= _STEM_MIN_ROOT_LENGTH:
            return stem[: -len(suffix)]

    return stem


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokenize(text: str) -> list[str]:
    """Découpe + désaccentue + réduit chaque token à sa racine (`_light_stem`).

    Le stemming est intégré ICI, au cœur du pipeline d'embedding existant :
    l'ingestion et la recherche passent toutes deux par cette fonction, donc
    documents et requêtes sont normalisés strictement de la même façon.
    """
    cleaned = _strip_accents(text.lower())
    tokens = [_light_stem(token) for token in _TOKEN_RE.findall(cleaned)]
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
        # Nom VERSIONNÉ (v2 = stemming léger + 1024 dimensions). ChromaDB
        # persiste ce nom dans la configuration de la collection et REFUSE de
        # l'ouvrir avec une fonction d'embedding portant un nom différent
        # (vérifié) — c'est la première barrière contre l'usage d'anciens
        # vecteurs. Le message natif de ChromaDB n'étant pas actionnable, il
        # est traduit en `FaqEmbeddingDimensionMismatchError` par
        # `get_faq_collection`. Toute évolution future du calcul d'embedding
        # doit incrémenter ce numéro de version.
        return "hashing-bag-of-words-v2"

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


class FaqEmbeddingDimensionMismatchError(RuntimeError):
    """Collection ChromaDB persistée avec un embedding obsolète (nom ou dimension).

    Levée par `get_faq_collection`. Toujours accompagnée de la marche à suivre
    (`python scripts/ingest_faq.py`) — voir `_assert_collection_dimension` et
    la traduction de l'erreur native ChromaDB dans `get_faq_collection`.
    """


def _obsolete_collection_error(collection_name: str, persist_dir: str, cause: str) -> FaqEmbeddingDimensionMismatchError:
    """Message d'erreur unique et actionnable pour les deux voies de détection
    (conflit de nom signalé par ChromaDB, ou dimension stockée différente)."""
    return FaqEmbeddingDimensionMismatchError(
        f"La collection ChromaDB '{collection_name}' a été créée par une version précédente "
        f"de l'embedding FAQ et n'est plus utilisable ({cause}). Ses vecteurs ne sont plus "
        f"comparables à ceux que produit le code actuel "
        f"(HashingBagOfWordsEmbedding v2 : stemming léger + {_VECTOR_DIM} dimensions). "
        f"Ré-ingérez la FAQ : python scripts/ingest_faq.py  (dossier concerné : {persist_dir})"
    )


# Collections déjà vérifiées pour ce process : `get_faq_collection` est appelée
# à CHAQUE requête (`backend/app/routers/chat.py`, dépendance FastAPI), on ne
# relit donc la dimension qu'une seule fois par (dossier, collection).
_VERIFIED_COLLECTIONS: set = set()


def _assert_collection_dimension(collection: Any, persist_dir: str, collection_name: str) -> None:
    """Refuse une collection dont les vecteurs stockés n'ont pas `_VECTOR_DIM`.

    Nécessaire car ChromaDB ne protège que partiellement : une différence de
    dimension finit certes par lever une erreur, mais seulement au moment d'un
    `add`/`query` — et son message ("Collection expecting embedding with
    dimension of 256, got 1024") n'indique pas la marche à suivre. Un
    changement du seul NOM de la fonction d'embedding, lui, ne lève rien du
    tout (vérifié) : c'est donc bien la dimension stockée qu'il faut contrôler.

    Vérification volontairement tolérante : une collection vide (jamais
    ingérée) ou une lecture qui échoue ne bloquent jamais l'appelant — seule
    une dimension réellement différente est une erreur.
    """
    key = (persist_dir, collection_name)
    if key in _VERIFIED_COLLECTIONS:
        return

    try:
        stored = collection.get(limit=1, include=["embeddings"])
        embeddings = stored.get("embeddings")
    except Exception:  # noqa: BLE001 — frontière SDK : jamais bloquer sur un aléa de lecture
        _VERIFIED_COLLECTIONS.add(key)
        return

    if embeddings is not None and len(embeddings) > 0:
        stored_dim = len(embeddings[0])
        if stored_dim != _VECTOR_DIM:
            raise _obsolete_collection_error(
                collection_name,
                persist_dir,
                f"dimension stockée {stored_dim}, attendue {_VECTOR_DIM}",
            )

    _VERIFIED_COLLECTIONS.add(key)


def get_faq_collection(
    persist_dir: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> Any:
    client = get_chroma_client(persist_dir)
    resolved_dir = _resolve_persist_dir(persist_dir) if persist_dir else DEFAULT_PERSIST_DIR
    resolved_name = collection_name or DEFAULT_COLLECTION_NAME
    try:
        collection = client.get_or_create_collection(
            name=resolved_name,
            embedding_function=HashingBagOfWordsEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )
    except ValueError as exc:
        # ChromaDB refuse d'ouvrir une collection dont la fonction d'embedding
        # persistée porte un autre nom (ex. "hashing-bag-of-words" v1 face à
        # "hashing-bag-of-words-v2"). Son message natif n'indique pas la marche
        # à suivre — on le traduit, sans jamais masquer un autre ValueError.
        if "embedding function" in str(exc).lower():
            raise _obsolete_collection_error(
                resolved_name, resolved_dir, "fonction d'embedding persistée différente"
            ) from exc
        raise

    _assert_collection_dimension(collection, resolved_dir, resolved_name)
    return collection


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
