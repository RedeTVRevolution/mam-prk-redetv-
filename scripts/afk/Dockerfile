# Ambiente do agente do loop AFK: ferramentas do projeto e nenhuma credencial de nuvem.
FROM python:3.12-slim-bookworm

ARG TARGETARCH
ARG CLAUDE_CODE_VERSION=2.1.312
ARG GH_VERSION=2.101.0
ARG GITLEAKS_VERSION=8.30.1
ARG TERRAFORM_VERSION=1.17.1
# O mesmo ffmpeg do Job de validação (Dockerfile, alvo validacao; o make verificar confere).
ARG FFMPEG=7:5.1.9-0+deb12u1

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /usr/local/bin/
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# O make verificar daqui testa o validador com este ffmpeg; por isso ele é o da produção.
RUN apt-get update \
 && (apt-get install -y --no-install-recommends ca-certificates curl ffmpeg=$FFMPEG git jq make unzip \
     || { echo "A instalação do ffmpeg $FFMPEG falhou. Se essa versão não está na lista abaixo, ela saiu do repositório do Debian: troque o ARG FFMPEG pela mesma versão nova no Dockerfile (alvo validacao) e no scripts/afk/Dockerfile." >&2; apt-cache madison ffmpeg >&2; exit 1; }) \
 && rm -rf /var/lib/apt/lists/*

RUN case "$TARGETARCH" in \
      arm64) gl=arm64; gl_sha=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;; \
      *) gl=x64; gl_sha=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;; \
    esac \
 && curl -sSfLo /tmp/gitleaks.tar.gz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gl}.tar.gz" \
 && echo "$gl_sha  /tmp/gitleaks.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
 && curl -sSfL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH:-amd64}.tar.gz" \
    | tar xz -C /usr/local --strip-components=1 \
 && rm /tmp/gitleaks.tar.gz \
 && case "$TARGETARCH" in \
      arm64) tf_sha=988e950a1c23058093b0e66ab2d5fb53fc18345ecfbd5871acf51dbac9325edd ;; \
      *) tf_sha=4638628058e71a55212b1c563712eac03b902128f40740f3dc8174df12135061 ;; \
    esac \
 && curl -sSfLo /tmp/terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH:-amd64}.zip" \
 && echo "$tf_sha  /tmp/terraform.zip" | sha256sum -c - \
 && unzip -q /tmp/terraform.zip terraform -d /usr/local/bin \
 && rm /tmp/terraform.zip \
 && terraform version \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && git config --system safe.directory '*'

# O Claude Code recusa --dangerously-skip-permissions como root.
RUN useradd -m agente
USER agente
ENV HOME=/home/agente UV_PYTHON_DOWNLOADS=never
