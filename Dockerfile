# O ffmpeg dos alvos validacao e ocr-gpu, o mesmo do scripts/afk/Dockerfile (o make verificar confere).
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

# Base da transcrição (#104): só o faster-whisper e o
# modelo, sem ffmpeg nem front. O modelo é baixado aqui, na construção, na revisão fixada
# e conferido pelo SHA-256 de cada arquivo; no ar o Job roda sem internet (HF_HUB_OFFLINE).
FROM python:3.12-slim-bookworm AS transcricao-base
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
ENV PATH=/app/.venv/bin:$PATH TMPDIR=/saida PASTA_DO_MODELO=/modelo HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1

# As amostras do teste dos Jobs com GPU (#238): uns segundos de fala, que o espeak-ng gera
# na construção (sem arquivo binário no repositório). A frase é a de `api/teste_dos_jobs.py`
# (`FRASE_FALADA`); o teste do repositório confere que as duas combinam. O quadro com
# `REDETV` nasce no alvo `ocr-gpu`, que tem o OpenCV.
FROM python:3.12-slim-bookworm AS amostras
RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /amostras \
    && espeak-ng -v pt-br -s 130 -w /amostras/fala.wav "Bom dia. Bom dia a todos."

# Job de transcrição em GPU (E1, ADR 0007): `docker build --target transcricao-gpu`. Parte do
# alvo `transcricao-base` (mesmo modelo, mesma revisão, mesmos hashes, sem baixar de novo) e
# acrescenta as bibliotecas CUDA 12 e cuDNN 9 que o CTranslate2 4 pede, como rodas do
# PyPI. O driver (580, CUDA 13) é do Cloud Run, que o monta em /usr/local/nvidia/lib64;
# um runtime CUDA 12 roda nele. Esta imagem só roda com GPU (`DISPOSITIVO=gpu`).
FROM transcricao-base AS transcricao-gpu
RUN uv sync --locked --no-dev --group transcricao --group transcricao-gpu
COPY --from=amostras /amostras /amostras
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/nvidia/lib64 \
    AMOSTRAS=/amostras DISPOSITIVO=gpu
# Só os módulos que o ponto de entrada importa (#388), para mudar outro módulo de `api/` não mudar
# esta imagem nem republicar e testar o Job com GPU: o teste do repositório confere a lista.
COPY api/__init__.py \
     api/auditoria.py \
     api/auth.py \
     api/catalogo.py \
     api/catalogo_apagado.py \
     api/catalogo_de_correcoes.py \
     api/catalogo_dos_jobs.py \
     api/chaves.py \
     api/ciclo_de_vida.py \
     api/comparador.py \
     api/correcoes.py \
     api/csv_seguro.py \
     api/decupagem.py \
     api/dispositivo.py \
     api/espera.py \
     api/eventos_de_uso.py \
     api/eventos_do_job.py \
     api/florence.py \
     api/idempotencia.py \
     api/identidade.py \
     api/indice_da_busca.py \
     api/itens_da_decupagem.py \
     api/janelas.py \
     api/jobs.py \
     api/leitura_da_tela.py \
     api/lixeira.py \
     api/log_estruturado.py \
     api/marcas.py \
     api/nuvem.py \
     api/paddle.py \
     api/papeis.py \
     api/pessoas.py \
     api/programas.py \
     api/progresso_das_janelas.py \
     api/revisao.py \
     api/sinais.py \
     api/teste_dos_jobs.py \
     api/texto_como_dado.py \
     api/tipos_de_objeto.py \
     api/transcricao.py \
     api/transcricao_job.py \
     api/usuarios.py \
     api/webhook.py \
     api/whisper.py api/
# A máquina da construção não tem GPU. Aqui se confere que as bibliotecas CUDA carregam e
# que o faster-whisper transcreve a amostra em CPU (a mesma conferência do teste depois da
# publicação, `MODO_TESTE=1`, que lá exige a GPU). Não se confere o driver, a GPU nem o
# CUDA em uso: isso é do teste depois da publicação e da primeira execução no dev (#240).
RUN /app/.venv/bin/python -c "import ctypes, ctranslate2; ctypes.CDLL('libcublas.so.12'); ctypes.CDLL('libcudnn.so.9'); from api.teste_dos_jobs import testar_transcricao; raise SystemExit(testar_transcricao('cpu', exigir_gpu=False))"
USER nobody
CMD ["python", "-m", "api.transcricao_job"]

# Job de OCR em GPU (E1, ADR 0007): `docker build --target ocr-gpu`. Modelos baixados
# pelo script, com detector `server`, e `paddlepaddle-gpu` 3.2.2 (CUDA 12.6, do índice
# do Paddle). O driver é do Cloud Run, em /usr/local/nvidia/lib64. As bibliotecas CUDA
# vêm das rodas `nvidia-*` (uv.lock), como no alvo `transcricao-gpu`.
FROM python:3.12-slim-bookworm AS ocr-gpu
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG FFMPEG
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ffmpeg=$FFMPEG libgl1 libglib2.0-0 libgomp1 \
        || { echo "A instalação do ffmpeg $FFMPEG falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque o ARG FFMPEG pela mesma versão nova no Dockerfile e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
    && rm -rf /var/lib/apt/lists/*
ARG DETECTOR=PP-OCRv5_server_det
COPY scripts/baixar-modelos-ocr.sh /usr/local/bin/baixar-modelos-ocr
RUN baixar-modelos-ocr "$DETECTOR"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group ocr-gpu
# Só os módulos que o ponto de entrada importa (#388), para mudar outro módulo de `api/` não mudar
# esta imagem nem republicar e testar o Job com GPU: o teste do repositório confere a lista.
COPY api/__init__.py \
     api/auditoria.py \
     api/auth.py \
     api/catalogo.py \
     api/catalogo_apagado.py \
     api/catalogo_de_correcoes.py \
     api/catalogo_dos_jobs.py \
     api/chaves.py \
     api/ciclo_de_vida.py \
     api/comparador.py \
     api/correcoes.py \
     api/csv_seguro.py \
     api/decupagem.py \
     api/dispositivo.py \
     api/espera.py \
     api/eventos_de_uso.py \
     api/eventos_do_job.py \
     api/florence.py \
     api/idempotencia.py \
     api/identidade.py \
     api/indice_da_busca.py \
     api/itens_da_decupagem.py \
     api/janelas.py \
     api/jobs.py \
     api/leitura_da_tela.py \
     api/lixeira.py \
     api/log_estruturado.py \
     api/marcas.py \
     api/mudanca_da_tela.py \
     api/nuvem.py \
     api/ocr_job.py \
     api/paddle.py \
     api/papeis.py \
     api/pessoas.py \
     api/programas.py \
     api/progresso_das_janelas.py \
     api/quadros.py \
     api/revisao.py \
     api/sinais.py \
     api/teste_dos_jobs.py \
     api/texto_como_dado.py \
     api/tipos_de_objeto.py \
     api/transcricao.py \
     api/usuarios.py \
     api/webhook.py \
     api/whisper.py api/
ENV PATH=/app/.venv/bin:$PATH HOME=/saida TMPDIR=/saida PASTA_DOS_MODELOS=/modelos AMOSTRAS=/amostras \
    LD_LIBRARY_PATH=/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cuda_cupti/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cufft/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cufile/lib:/app/.venv/lib/python3.12/site-packages/nvidia/curand/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cusolver/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cusparse/lib:/app/.venv/lib/python3.12/site-packages/cusparselt/lib:/app/.venv/lib/python3.12/site-packages/nvidia/nccl/lib:/app/.venv/lib/python3.12/site-packages/nvidia/nvjitlink/lib:/app/.venv/lib/python3.12/site-packages/nvidia/nvtx/lib:/usr/local/nvidia/lib64 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONDONTWRITEBYTECODE=1 DISPOSITIVO=gpu DETECTOR=$DETECTOR
# A máquina da construção não tem GPU nem o driver, e o `paddlepaddle-gpu` pede o
# `libcuda.so.1` (do driver) já no `import paddle`: aqui ele não pode ser importado. Esta
# etapa só grava o quadro de amostra (do teste depois da publicação, `MODO_TESTE=1`),
# confere que o cuBLAS e o cuDNN das rodas carregam pelo LD_LIBRARY_PATH e que a roda
# instalada é a de GPU. Os modelos e o PaddleOCR são os mesmos do alvo
# `ocr`, que os confere em CPU na construção; a roda, o driver e a GPU são do teste depois da
# publicação (#238), que volta a imagem anterior se falhar.
RUN mkdir /amostras \
    && /app/.venv/bin/python -c "import ctypes, cv2, numpy; ctypes.CDLL('libcublas.so.12'); ctypes.CDLL('libcudnn.so.9'); from importlib.metadata import distributions; q = numpy.zeros((480, 854, 3), numpy.uint8); cv2.putText(q, 'REDETV', (200, 260), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 8); assert cv2.imwrite('/amostras/quadro.png', q); nomes = {d.metadata['Name'].lower() for d in distributions()}; assert 'paddlepaddle-gpu' in nomes and 'paddlepaddle' not in nomes, sorted(n for n in nomes if 'paddle' in n)"
USER nobody
CMD ["python", "-m", "api.ocr_job"]

# Job de objetos em GPU (E1, ADR 0008): `docker build --target objetos-gpu`. Florence-2
# (conversão oficial para o transformers, sem `trust_remote_code`), baixado aqui, na
# construção, na revisão fixada e conferido pelo SHA-256 de cada arquivo; no ar o Job roda
# sem internet. O quadro de amostra do teste (um carro, `OBJETO_DO_QUADRO` em
# `api/teste_dos_jobs.py`) vem de um dataset público da Hugging Face, numa revisão fixada
# e conferido pelo hash. O driver é do Cloud Run, em /usr/local/nvidia/lib64.
FROM python:3.12-slim-bookworm AS objetos-gpu
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv
ARG MODELO=florence-community/Florence-2-large
ARG MODELO_REVISAO=4271c66b88cdbc05735372ec13b2360108de5317
ARG AMOSTRA_REVISAO=9dd8e4710f6b2ddf5184d308639e0359bc7b55be
# Os pesos e a amostra vêm antes do `uv sync` (#211): só uma mudança deles os baixa de
# novo. O download usa só o urllib, do Python da imagem base.
RUN mkdir -p /modelo /amostras \
    && for arquivo in config.json generation_config.json model.safetensors preprocessor_config.json processor_config.json tokenizer.json tokenizer_config.json added_tokens.json merges.txt special_tokens_map.json vocab.json; do \
        python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
          "https://huggingface.co/$MODELO/resolve/$MODELO_REVISAO/$arquivo" "/modelo/$arquivo" || exit 1; \
    done \
    && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
        "https://huggingface.co/datasets/huggingface/documentation-images/resolve/$AMOSTRA_REVISAO/transformers/tasks/car.jpg" /amostras/objetos.jpg \
    && echo "8412483f687f2f71587328a38c6fa70a68d9488f28e90607be3c182641f60f2c  /modelo/config.json" > /tmp/hashes \
    && echo "0251459c49cc358ac033b5d4b8569e61ac22bde5d76be404b97a44cfb33fb12e  /modelo/generation_config.json" >> /tmp/hashes \
    && echo "7715423d6549bf1e71188bdd84f4ac960cc0597886af24a5ef7b66f128660685  /modelo/model.safetensors" >> /tmp/hashes \
    && echo "1396ec5a0a7adfe1c04fb777b09e8ba753be6dbb5868212ab3c3ef39d91fe031  /modelo/preprocessor_config.json" >> /tmp/hashes \
    && echo "cd0e3bf41a39b1276503fbd273bc03b9afc70d7a15ea681a92a1b4b77f858ee6  /modelo/processor_config.json" >> /tmp/hashes \
    && echo "3ad7001f773409abe6bba33eac92662611a73d72f459bda2f00d2a221dd31ce4  /modelo/tokenizer.json" >> /tmp/hashes \
    && echo "cb5f80bd9afa767bb1bb798ee5f0a79eae45239b8e72506166b4218175a16723  /modelo/tokenizer_config.json" >> /tmp/hashes \
    && echo "1d75deda84dfa81fb6c09301f3fed00f9695059568bbb1403a6bf299cd84fc37  /modelo/added_tokens.json" >> /tmp/hashes \
    && echo "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5  /modelo/merges.txt" >> /tmp/hashes \
    && echo "72ff172dc769bc1551b1b4211628ce3271643bc60379e4da45d85a9be9332c39  /modelo/special_tokens_map.json" >> /tmp/hashes \
    && echo "ed19656ea1707df69134c4af35c8ceda2cc9860bf2c3495026153a133670ab5e  /modelo/vocab.json" >> /tmp/hashes \
    && echo "8cd28b372908bcaa704a438965f8de47238c9514d5efefa89c510b82032f9d18  /amostras/objetos.jpg" >> /tmp/hashes \
    && sha256sum -c /tmp/hashes && rm /tmp/hashes
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group objetos
# Só os módulos que o ponto de entrada importa (#388), para mudar outro módulo de `api/` não mudar
# esta imagem nem republicar e testar o Job com GPU: o teste do repositório confere a lista.
COPY api/__init__.py \
     api/auditoria.py \
     api/auth.py \
     api/catalogo.py \
     api/catalogo_apagado.py \
     api/catalogo_de_correcoes.py \
     api/catalogo_dos_jobs.py \
     api/chaves.py \
     api/ciclo_de_vida.py \
     api/comparador.py \
     api/correcoes.py \
     api/csv_seguro.py \
     api/decupagem.py \
     api/dispositivo.py \
     api/espera.py \
     api/eventos_de_uso.py \
     api/florence.py \
     api/idempotencia.py \
     api/identidade.py \
     api/indice_da_busca.py \
     api/itens_da_decupagem.py \
     api/janelas.py \
     api/jobs.py \
     api/leitura_da_tela.py \
     api/lixeira.py \
     api/log_estruturado.py \
     api/marcas.py \
     api/nuvem.py \
     api/objetos_job.py \
     api/paddle.py \
     api/papeis.py \
     api/pessoas.py \
     api/programas.py \
     api/progresso_das_janelas.py \
     api/revisao.py \
     api/sinais.py \
     api/teste_dos_jobs.py \
     api/texto_como_dado.py \
     api/tipos_de_objeto.py \
     api/transcricao.py \
     api/usuarios.py \
     api/webhook.py \
     api/whisper.py api/
ENV PATH=/app/.venv/bin:$PATH HOME=/saida TMPDIR=/saida PASTA_DO_MODELO=/modelo AMOSTRAS=/amostras \
    LD_LIBRARY_PATH=/usr/local/nvidia/lib64 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PYTHONDONTWRITEBYTECODE=1 DISPOSITIVO=gpu
# A máquina da construção não tem GPU: confere que o torch e o transformers instalam e que o
# Florence-2 acha o carro da amostra (a mesma conferência do teste depois da publicação,
# `MODO_TESTE=1`, que lá exige a GPU) em CPU, com os pesos da imagem. Não pega o driver nem
# a GPU: isso é do teste depois da publicação (#238) e do dev (#240).
RUN HOME=/tmp/objetos TMPDIR=/tmp /app/.venv/bin/python -c "from api.teste_dos_jobs import testar_objetos; raise SystemExit(testar_objetos('cpu', exigir_gpu=False))" \
    && rm -rf /tmp/objetos
USER nobody
CMD ["python", "-m", "api.objetos_job"]

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
