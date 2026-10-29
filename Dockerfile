# Serviço único da E0: o FastAPI serve a API e o build do React.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Chave web do Identity Platform, pública, vinda do Terraform; sem ela o login fica indisponível.
ARG VITE_IDENTITY_API_KEY=""
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY api/ api/
COPY --from=web /web/dist web/dist
USER nobody
ENV PATH=/app/.venv/bin:$PATH
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
