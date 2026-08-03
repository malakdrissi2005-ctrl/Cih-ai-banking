"""Backend FastAPI — Agent 1 (FAQ publique) + fondation d'authentification.

Voir `CLAUDE.md` et `DocsContext/02_architecture_multi_agents.md` : l'Agent 1
est un module Python intégré à ce Backend (pas de service séparé, pas de
port dédié). L'authentification ici implémentée est une fondation de
démonstration : session opaque en SQLite (`app/security/session_manager.py`,
CLAUDE.md §4), sans JWT. `POST /api/chat` reste inchangé et ne consulte pas
encore cette session (les réponses personnelles de l'Agent 1 sont hors
périmètre). Ce fichier ne couvre volontairement pas : Agent 2, le protocole
A2A, MCP, n8n, ni la base bancaire.
"""
from __future__ import annotations

import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# Monorepo sans packaging global : `agents/` est un frère de `backend/`, pas
# un sous-package de `app`. La commande documentée (`03_stack_technique.md`
# §5.2) démarre uvicorn depuis `backend/` — on ajoute donc la racine du dépôt
# à sys.path pour que `import agents.agent1_faq...` fonctionne, sans changer
# cette commande.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env", override=False)  # silencieux si absent

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from agents.agent1_faq import llm_router  # noqa: E402
from app.routers import auth, chat  # noqa: E402

_DEMO_HTML_PATH = Path(__file__).resolve().parent / "templates" / "demo.html"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Réchauffement Ollama en tâche de fond (voir `llm_router.warm_up` :
    # chargement du modèle mesuré à ~45-53 s à froid sur cet environnement).
    # Lancé dans un thread séparé pour ne jamais retarder le démarrage du
    # backend, et seulement si le routeur LLM est activé et configuré — sinon
    # no-op silencieux, exactement comme un appel `route_with_llm` en échec.
    if llm_router.is_router_enabled() and llm_router.is_llm_configured():
        threading.Thread(target=llm_router.warm_up, daemon=True).start()
    yield


app = FastAPI(
    title="CIH AI Banking — Backend (Agent 1, périmètre pré-authentification)",
    version="0.1.0",
    lifespan=_lifespan,
)

# CORS : nécessaire pour que le frontend Vite (dev server, port 5173) puisse
# appeler cette API depuis le navigateur (origine différente : 8000 vs 5173).
# Restreint aux seules origines de développement local du frontend existant.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(chat.router)
app.include_router(auth.router)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def demo_page() -> str:
    return _DEMO_HTML_PATH.read_text(encoding="utf-8")
