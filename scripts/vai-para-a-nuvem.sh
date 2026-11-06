#!/usr/bin/env bash
# Usado pelo CI (job `mudou-o-deploy` e passo `ponta` do `publicar`): lê na entrada os caminhos
# que mudaram, um por linha, e sai com 0 se algum deles vai para a nuvem no `make deploy-dev`
# (imagens do Cloud Build ou `terraform apply`), e com 1 se nenhum vai. A lista é do que NÃO
# publica: um caminho fora dela publica, inclusive um novo. Na dúvida, o caminho publica.
set -euo pipefail

while IFS= read -r caminho; do
  case $caminho in
    '') ;;
    # Fora da imagem (.dockerignore) e do Terraform: só os testes leem.
    api/tests/*) ;;
    # api/ e web/ vão inteiros para a imagem, inclusive um .md.
    api/* | web/*) exit 0 ;;
    # Fora da imagem (o .dockerignore só libera api/, web/, pyproject.toml, uv.lock e
    # scripts/baixar-modelos-ocr.sh) e fora do infra/ que o Terraform lê (só *.tf e os
    # arquivos do módulo pelo path.module; o README.md não entra).
    docs/* | evals/* | prototipos/* | scripts/afk/* | .afk/* | .claude/* | .codex/* | .githooks/*) ;;
    # O .gitignore entra no .gcloudignore, mas só tira arquivos do envio: o que ele muda na
    # imagem não é um deploy que se quer, e o próximo deploy o leva do mesmo jeito.
    *.md | .gitignore) ;;
    *) exit 0 ;;
  esac
done
exit 1
