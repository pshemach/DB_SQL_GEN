FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PYTHON=/usr/local/bin/python
ENV UV_SYSTEM_PYTHON=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project

# Optional: install pip into .venv
RUN uv pip install pip --python /app/.venv/bin/python

COPY . .

EXPOSE 8558

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8558"]