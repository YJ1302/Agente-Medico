"""Repository layer — data access isolated from business logic.

Repositories are the ONLY place that build SQLAlchemy queries. Services depend
on repositories, never on the ORM session directly for query construction.
This keeps a future storage/engine change (e.g. PostgreSQL) contained here.
"""
