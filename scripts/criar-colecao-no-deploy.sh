#!/usr/bin/env bash
# Cria (ou completa) as coleções e o índice da busca durante o deploy (#757), como a mam-terraform:
# GCP_PROJECT_ID e GOOGLE_IMPERSONATE_SERVICE_ACCOUNT vêm do chamador. Roda depois do primeiro
# apply (o direcionado) e antes do build. Os seis valores vêm do Terraform (ponto único, #756) e
# o deploy nunca liga o índice ANN por conta própria: BUSCA_INDICES_LIGADOS segue o output.
# Não exige busca_consultas_por_minuto nem busca_aceita_teste_de_carga: esses leem o serviço web.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

lido=$(PASTA_DO_AMBIENTE=infra scripts/ler-ambiente.sh --deploy BUSCA_REGIAO BUSCA_COLECAO \
  BUSCA_COLECAO_DE_TEXTO BUSCA_INDICE_DESCRICAO BUSCA_DIMENSAO BUSCA_INDICES_LIGADOS) || exit 1
# As demais BUSCA_* herdadas do arquivo de ambiente (cota, distância) não entram: o
# ConfigDaBusca.do_ambiente converteria um valor local inválido.
for v in $(compgen -e | grep '^BUSCA_' || true); do unset "$v"; done
eval "$lido"
export BUSCA_REGIAO BUSCA_COLECAO BUSCA_COLECAO_DE_TEXTO BUSCA_INDICE_DESCRICAO BUSCA_DIMENSAO BUSCA_INDICES_LIGADOS

saida=$(mktemp)
trap 'rm -f "$saida"' EXIT
if ! uv run --locked python -m api.criar_colecao_da_busca 2>&1 | tee "$saida"; then
  echo "A criação das coleções da busca falhou (a causa está acima): corrija e rode o deploy de novo." >&2
  exit 1
fi
if grep -q 'make reindexar' "$saida"; then
  echo "Aviso: o esquema da busca ganhou campos; rode \`make reindexar\`." | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}" >&2
fi
