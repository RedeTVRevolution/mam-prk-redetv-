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
# O mesmo ffmpeg do scripts/afk/Dockerfile (o make verificar confere): o loop AFK testa o validador com ele.
ARG FFMPEG=7:5.1.9-0+deb12u1
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ffmpeg=$FFMPEG \
        || { echo "A instalação do ffmpeg $FFMPEG falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque o ARG FFMPEG pela mesma versão nova no Dockerfile (alvo validacao) e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY api/ api/
USER nobody
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.validacao_job"]

# Job de transcrição (#104): `docker build --target transcricao`. Só o faster-whisper e o
# modelo, sem ffmpeg nem front. O modelo é baixado aqui, na construção, na revisão fixada
# e conferido pelo SHA-256 do model.bin; no ar o Job roda sem internet (HF_HUB_OFFLINE).
FROM python:3.12-slim-bookworm AS transcricao
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG MODELO_REPOSITORIO=dropbox-dash/faster-whisper-large-v3-turbo
ARG MODELO_REVISAO=0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf
ARG MODELO_SHA256=e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group transcricao
RUN /app/.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('$MODELO_REPOSITORIO', revision='$MODELO_REVISAO', local_dir='/modelo')" \
    && echo "$MODELO_SHA256  /modelo/model.bin" | sha256sum -c - \
    && rm -rf /modelo/.cache
COPY api/ api/
USER nobody
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PASTA_DO_MODELO=/modelo HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.transcricao_job"]

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
