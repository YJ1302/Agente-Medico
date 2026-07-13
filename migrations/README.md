# Database migrations (Alembic)

The schema is managed by Alembic. See `docs/DEVELOPMENT_GUIDE.md` for the full
workflow. Common commands (run from the project root with the venv active):

```bat
alembic upgrade head            :: apply all migrations
alembic revision --autogenerate -m "message"   :: create a migration from model changes
alembic downgrade -1            :: revert the last migration
alembic history                 :: list migrations
alembic current                 :: show the current revision
```

The database URL is taken from `app.config` (the `.env` `DATABASE_URL`), so no
URL is hardcoded in `alembic.ini`.
