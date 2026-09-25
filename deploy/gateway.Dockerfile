# Gateway intake image (story 1.1, AD-17/AD-25): Starlette + uvicorn + pinned
# psycopg. The same image runs under Compose and plain k8s (AD-25).
FROM python:3.14-slim-trixie

RUN pip install --no-cache-dir \
    "psycopg[binary]==3.3.6" \
    "starlette==1.7.0" \
    "uvicorn==0.54.0" \
    "pydantic==2.13.5" \
    "PyYAML==6.0.3" \
    "click==8.5.0" \
    "h11==0.16.0"

COPY gateway/ /app/gateway/
COPY workflow/__init__.py /app/workflow/__init__.py
COPY workflow/run_states.py /app/workflow/run_states.py
COPY workflow/ids.py /app/workflow/ids.py
COPY config/gateway.yaml /app/config/gateway.yaml

WORKDIR /app
CMD ["python", "-m", "gateway"]
