"""General Agent — répond aux questions non bancaires via l'API Google Gemini.

Séparé du Banking Agent (`agents/agent1_faq/`, jamais modifié par ce module) :
ne reçoit et ne traite jamais de question bancaire, n'accède jamais à
`banking_db`, ChromaDB, ni `auth.db`. Voir `general_agent.py`, `gemini_client.py`.
"""
