# Backend FastAPI (Agent 1 integre) — voir CLAUDE.md, DocsContext/03_stack_technique.md.
#
# Construit avec la racine du monorepo comme contexte de build (voir
# docker-compose.yml : `context: .`, `dockerfile: backend/Dockerfile`), pour
# pouvoir copier `agents/` en plus de `backend/`. La resolution des chemins
# existante (`_REPO_ROOT` dans banking_db.py / session_manager.py / rag.py /
# main.py, calculee via `Path(__file__).resolve().parents[N]`) suppose la
# meme structure relative que le depot — ce Dockerfile la reproduit a
# l'identique dans l'image (/app = racine du depot), sans aucun changement de
# code ni d'architecture de l'Agent 1.
FROM python:3.11-slim

WORKDIR /app

# Dependances d'abord (couche mise en cache separement du code applicatif).
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Code applicatif — uniquement ce dont le Backend + Agent 1 ont besoin a
# l'execution. Ni frontend/, ni mock-banking-api/, ni mcp-server/, ni
# DocsContext/ : hors perimetre de ce conteneur.
COPY agents/ agents/
COPY backend/app/ backend/app/
COPY data/ data/
COPY scripts/ scripts/

# auth.db, backend/data/banking.db, chroma_db/ sont montes en volumes depuis
# l'hote (voir docker-compose.yml) — jamais copies dans l'image, pour ne
# jamais figer ni ecraser les donnees existantes au moment du build.

WORKDIR /app/backend

EXPOSE 8000

# Reproduit exactement la commande documentee (DocsContext/03_stack_technique.md
# §5.2) : `cd backend && uvicorn app.main:app --port 8000`, sans --reload
# (non pertinent en conteneur de demonstration).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
