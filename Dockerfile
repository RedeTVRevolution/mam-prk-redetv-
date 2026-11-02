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
# e conferido pelo SHA-256 de cada arquivo; no ar o Job roda sem internet (HF_HUB_OFFLINE).
FROM python:3.12-slim-bookworm AS transcricao
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG MODELO_REPOSITORIO=dropbox-dash/faster-whisper-large-v3-turbo
ARG MODELO_REVISAO=0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf
ARG MODELO_SHA256=e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da
# O modelo vem antes do `uv sync` (#211): só uma mudança de modelo o baixa de novo. O
# download usa só o urllib, do Python da imagem base, como o do OCR.
RUN mkdir /modelo && for arquivo in config.json model.bin preprocessor_config.json tokenizer.json vocabulary.json; do \
      python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
        "https://huggingface.co/$MODELO_REPOSITORIO/resolve/$MODELO_REVISAO/$arquivo" "/modelo/$arquivo" || exit 1; \
    done \
    && echo "$MODELO_SHA256  /modelo/model.bin" > /tmp/hashes \
    && echo "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e  /modelo/config.json" >> /tmp/hashes \
    && echo "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711  /modelo/preprocessor_config.json" >> /tmp/hashes \
    && echo "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd  /modelo/tokenizer.json" >> /tmp/hashes \
    && echo "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1  /modelo/vocabulary.json" >> /tmp/hashes \
    && sha256sum -c /tmp/hashes && rm /tmp/hashes
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group transcricao
# Os testes usam um modelo falso: aqui o faster-whisper decodifica um WAV de verdade pelo
# PyAV instalado, para a imagem não ser construída com versões que não conversam.
RUN /app/.venv/bin/python -c "import wave; w = wave.open('/tmp/s.wav', 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(32000)); w.close(); from faster_whisper.audio import decode_audio; assert len(decode_audio('/tmp/s.wav')) == 16000" \
    && rm /tmp/s.wav
COPY api/ api/
USER nobody
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PASTA_DO_MODELO=/modelo HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.transcricao_job"]

# Job de transcrição em GPU (E1, ADR 0007): `docker build --target transcricao-gpu`. Parte do
# alvo `transcricao` (mesmo modelo, mesma revisão, mesmos hashes, sem baixar de novo) e
# acrescenta as bibliotecas CUDA 12 e cuDNN 9 que o CTranslate2 4 pede, como rodas do
# PyPI. O driver (580, CUDA 13) é do Cloud Run, que o monta em /usr/local/nvidia/lib64;
# um runtime CUDA 12 roda nele. Esta imagem só roda com GPU (`DISPOSITIVO=gpu`).
FROM transcricao AS transcricao-gpu
USER root
RUN uv sync --locked --no-dev --group transcricao --group transcricao-gpu
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/nvidia/lib64 \
    DISPOSITIVO=gpu
# A máquina da construção não tem GPU. Aqui se confere que as bibliotecas CUDA carregam e
# que o faster-whisper roda o modelo e a detecção de voz em CPU. Não se confere o driver, a
# GPU nem o CUDA em uso: isso é da primeira execução no dev (240).
RUN /app/.venv/bin/python -c "import ctypes, wave; import ctranslate2; ctypes.CDLL('libcublas.so.12'); ctypes.CDLL('libcudnn.so.9'); w = wave.open('/tmp/s.wav', 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(64000)); w.close(); from api.whisper import VAD_PARAMETROS; from faster_whisper import WhisperModel; m = WhisperModel('/modelo', device='cpu', compute_type='int8', local_files_only=True); segmentos, _ = m.transcribe('/tmp/s.wav', language='pt', word_timestamps=True, vad_filter=True, vad_parameters=VAD_PARAMETROS); assert list(segmentos) == []" \
    && rm /tmp/s.wav
USER nobody

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
# Os modelos vêm antes do `uv sync` (#211): só uma mudança de modelo os baixa de novo. O
# download usa só o urllib, do Python da imagem base.
RUN baixar() { \
      mkdir -p "/modelos/$1" && for arquivo in config.json inference.json inference.pdiparams inference.yml; do \
        python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
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
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group ocr
COPY api/ api/
# Os testes usam um modelo falso: aqui o PaddleOCR lê um quadro de verdade com os modelos
# da imagem, para a imagem não ser construída com uma versão que não roda em CPU.
RUN HOME=/tmp/ocr PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True /app/.venv/bin/python -c "import cv2, numpy; q = numpy.zeros((480, 854, 3), numpy.uint8); cv2.putText(q, 'REDETV', (200, 260), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 8); cv2.imwrite('/tmp/ocr.png', q); from pathlib import Path; from api.paddle import LeitorPaddle; assert [l.texto for l in LeitorPaddle.da_pasta('/modelos').ler(Path('/tmp/ocr.png'))] == ['REDETV']" \
    && rm -rf /tmp/ocr /tmp/ocr.png
USER nobody
# HOME e TMPDIR no volume em memória: o Paddle grava cache e o ffmpeg, os quadros, e a imagem não tem pasta gravável.
ENV PATH=/app/.venv/bin:$PATH HOME=/saida TMPDIR=/saida PASTA_DOS_MODELOS=/modelos \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "api.ocr_job"]

# Job de OCR em GPU (E1, ADR 0007): `docker build --target ocr-gpu`. Os mesmos modelos do
# alvo `ocr`, copiados dele (mesmas revisões e hashes), e o `paddlepaddle-gpu` 3.2.2 (CUDA
# 12.6, do índice do Paddle) no lugar do `paddlepaddle` de CPU. Não parte do alvo `ocr` para
# não carregar a roda de CPU. O driver é do Cloud Run, em /usr/local/nvidia/lib64.
FROM python:3.12-slim-bookworm AS ocr-gpu
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG FFMPEG
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ffmpeg=$FFMPEG libgl1 libglib2.0-0 libgomp1 \
        || { echo "A instalação do ffmpeg $FFMPEG falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque o ARG FFMPEG pela mesma versão nova no Dockerfile e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ocr /modelos /modelos
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group ocr-gpu
COPY api/ api/
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64
# A máquina da construção não tem GPU: o Paddle lê um quadro de verdade em CPU, com os
# modelos da imagem. Isso pega roda que não instala, biblioteca CUDA que não carrega e
# modelo incompatível; não pega o driver nem a GPU (primeira execução no dev, 240).
RUN HOME=/tmp/ocr PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True /app/.venv/bin/python -c "import cv2, numpy, paddle; assert paddle.device.is_compiled_with_cuda(); q = numpy.zeros((480, 854, 3), numpy.uint8); cv2.putText(q, 'REDETV', (200, 260), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 8); cv2.imwrite('/tmp/ocr.png', q); from pathlib import Path; from api.paddle import LeitorPaddle; assert [l.texto for l in LeitorPaddle.da_pasta('/modelos', 'cpu').ler(Path('/tmp/ocr.png'))] == ['REDETV']" \
    && rm -rf /tmp/ocr /tmp/ocr.png
USER nobody
ENV PATH=/app/.venv/bin:$PATH HOME=/saida TMPDIR=/saida PASTA_DOS_MODELOS=/modelos \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONDONTWRITEBYTECODE=1 DISPOSITIVO=gpu
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
