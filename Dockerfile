# Hugging Face Docker Space: Website Audit Agent web demo.
FROM python:3.12-slim

# uv, pinned. Keep this in step with the local version (`uv --version`) so it reads uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# Spaces run the container as user 1000.
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/app/.venv/bin:$PATH \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    AUDIT_CACHE_DIR=/tmp/website-audit-cache
WORKDIR /home/user/app

# Dependencies first (cached layer), then the code.
COPY --chown=user pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra web --no-install-project
COPY --chown=user src ./src
RUN uv sync --frozen --no-dev --extra web

EXPOSE 7860

# GEMINI_API_KEY comes from a Space secret at runtime; it is never baked into the image.
# --no-access-log: logs keep only time, host and result, never full URLs (web decision 8).
CMD ["uvicorn", "website_audit_agent.web.app:build_default_app", "--factory", "--host", "0.0.0.0", "--port", "7860", "--no-access-log"]
