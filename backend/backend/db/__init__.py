# AGENT-CTX: db/ is the persistence layer for all stateful entities (jobs, and
# future notes/annotations per graph/conversation). Keep domain logic out of this
# package — it owns only DB I/O and the Pydantic shapes that mirror DB rows.
