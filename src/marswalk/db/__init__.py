"""SQLite persistence. ONLY `marswalk.db` (models, engine, repo) may touch SQLAlchemy.

Everything else, including the API routes, goes through the functions in `marswalk.db.repo`.
tests/test_architecture.py enforces this boundary.
"""
