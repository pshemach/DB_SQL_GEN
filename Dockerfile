FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Tell uv to use system Python, not download/find exact managed Python
ENV UV_PYTHON=/usr/local/bin/python
ENV UV_SYSTEM_PYTHON=1

# Copy dependency files first
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --locked --no-dev --no-install-project

# Copy app source
COPY . .

EXPOSE 8558

CMD ["uv", "run", "--python", "/usr/local/bin/python", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8558"]