# Serviço único da E0: o FastAPI serve a API e o build do React.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Chave web do Identity Platform, pública, vinda do Terraform; sem ela o login fica indisponível.
ARG VITE_IDENTITY_API_KEY=""
RUN npm run build

# Job de validação (#38): `docker build --target validacao`. Sem o build do front.
# Usuário sem privilégios e nenhuma pasta da imagem gravável: o TMPDIR aponta para
# o volume em memória que o Cloud Run monta em /saida, a única pasta gravável.
FROM python:3.12-slim-bookworm AS validacao
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
# O mesmo ffmpeg do scripts/afk/Dockerfile: o loop AFK testa o validador com ele.
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 \
        || { echo "A instalação do ffmpeg 7:5.1.9-0+deb12u1 falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque-a pela mesma versão nova no Dockerfile (alvo validacao) e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY api/ api/
USER nobody
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.validacao_job"]

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
