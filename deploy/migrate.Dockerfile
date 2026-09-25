# One-shot migration job image (story 0.3, AD-25): runner + pinned psycopg.
# Later stories replace this with the shared worker images — same base rules.
FROM python:3.14-slim-trixie

RUN pip install --no-cache-dir "psycopg[binary]==3.3.6"

COPY workflow/__init__.py /app/workflow/__init__.py
COPY workflow/migrate.py /app/workflow/migrate.py
# Source migrations come from deploy/migrations via a read-only bind mount
# (set by deploy/compose.yaml), so adding a migration never needs a rebuild.

WORKDIR /app
ENTRYPOINT ["python", "-m", "workflow.migrate", "--migrations-dir", "/migrations"]
