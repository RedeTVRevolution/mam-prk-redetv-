# O ffmpeg dos alvos validacao e ocr, o mesmo do scripts/afk/Dockerfile (o make verificar confere).
# Antes do primeiro FROM, para valer em todos os estágios que o declaram com `ARG FFMPEG`.
ARG FFMPEG=7:5.1.9-0+deb12u1

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
ARG FFMPEG
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
# Os testes usam um modelo falso: aqui o faster-whisper decodifica um WAV de verdade pelo
# PyAV instalado, para a imagem não ser construída com versões que não conversam.
RUN /app/.venv/bin/python -c "import wave; w = wave.open('/tmp/s.wav', 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(32000)); w.close(); from faster_whisper.audio import decode_audio; assert len(decode_audio('/tmp/s.wav')) == 16000" \
    && rm /tmp/s.wav
RUN /app/.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('$MODELO_REPOSITORIO', revision='$MODELO_REVISAO', local_dir='/modelo')" \
    && echo "$MODELO_SHA256  /modelo/model.bin" | sha256sum -c - \
    && rm -rf /modelo/.cache
COPY api/ api/
USER nobody
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PASTA_DO_MODELO=/modelo HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.transcricao_job"]

# Job de OCR da tela (#106): `docker build --target ocr`. ffmpeg para os quadros, PaddleOCR
# e os dois modelos, baixados aqui, na construção, nas revisões fixadas e conferidos pelo
# SHA-256 de cada arquivo; no ar o Job roda sem internet.
FROM python:3.12-slim-bookworm AS ocr
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG FFMPEG
ARG DETECTOR=PP-OCRv5_server_det
ARG DETECTOR_REVISAO=ca867c897ecbca8873081573a802ad70d499cb94
ARG DETECTOR_SHA256=183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d
ARG RECONHECEDOR=latin_PP-OCRv5_mobile_rec
ARG RECONHECEDOR_REVISAO=ab2cd5cc5fa6309be2e5acdfe66eca2c2c127d57
ARG RECONHECEDOR_SHA256=53cdc8b481a7394bb108f96d0fb3432b0a8f392e22c7d18f06dbb2d42b8b25f9
# As bibliotecas do OpenCV (libgl1, libglib2.0-0) e do Paddle (libgomp1).
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ffmpeg=$FFMPEG libgl1 libglib2.0-0 libgomp1 \
        || { echo "A instalação do ffmpeg $FFMPEG falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque o ARG FFMPEG pela mesma versão nova no Dockerfile e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group ocr
RUN baixar() { \
      mkdir -p "/modelos/$1" && for arquivo in config.json inference.json inference.pdiparams inference.yml; do \
        /app/.venv/bin/python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
          "https://huggingface.co/PaddlePaddle/$1/resolve/$2/$arquivo" "/modelos/$1/$arquivo" || return 1; \
      done; \
    } \
    && baixar "$DETECTOR" "$DETECTOR_REVISAO" \
    && baixar "$RECONHECEDOR" "$RECONHECEDOR_REVISAO" \
    && echo "$DETECTOR_SHA256  /modelos/$DETECTOR/inference.pdiparams" > /tmp/hashes \
    && echo "436bf19010fe3879477e8599a870a0ec8ccd14ca39056805ec4ed20ab318ec04  /modelos/$DETECTOR/config.json" >> /tmp/hashes \
    && echo "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28  /modelos/$DETECTOR/inference.json" >> /tmp/hashes \
    && echo "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685  /modelos/$DETECTOR/inference.yml" >> /tmp/hashes \
    && echo "$RECONHECEDOR_SHA256  /modelos/$RECONHECEDOR/inference.pdiparams" >> /tmp/hashes \
    && echo "e0f5ccc44fe86254956f27746058bc4cf88d86145668cecf22ba5dd962483c80  /modelos/$RECONHECEDOR/config.json" >> /tmp/hashes \
    && echo "820b2ee8e5072de5156c3d55124c2b03c82ef278d59f453f857c0789bacb4da1  /modelos/$RECONHECEDOR/inference.json" >> /tmp/hashes \
    && echo "0bbe984570f597af3638e50bdf2e8276f3ab26a61966096538b3b0d1849f5c84  /modelos/$RECONHECEDOR/inference.yml" >> /tmp/hashes \
    && sha256sum -c /tmp/hashes && rm /tmp/hashes
COPY api/ api/
USER nobody
# HOME e TMPDIR no volume em memória: o Paddle grava cache e o ffmpeg, os quadros, e a imagem não tem pasta gravável.
ENV PATH=/app/.venv/bin:$PATH HOME=/saida TMPDIR=/saida PASTA_DOS_MODELOS=/modelos \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.ocr_job"]

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
