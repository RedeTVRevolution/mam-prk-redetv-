#!/usr/bin/env bash
# O ponto único que lê os outputs do Terraform (#756): roda `terraform output -json` uma vez, na
# pasta do ambiente, e imprime no stdout, para o chamador dar `eval`, uma atribuição por item pedido.
# O JSON nunca é impresso (há output `sensitive`, como identity_api_key).
#
#   ambiente=$(scripts/ler-ambiente.sh [--deploy] ITEM...) && eval "$ambiente"
#
# ITEM é `VAR` (o output tem o nome da variável em minúsculas, salvo as duas exceções abaixo),
# `VAR=output` ou, com `:opcional` no fim, opcional (ausente vira vazio, sem erro).
# Nos alvos locais, `export VAR=...`, e a variável que já vem no ambiente da pessoa fica como está
# (sem ler o Terraform se nenhuma faltar). Com --deploy, só `VAR=...` (sem export), o valor do
# Terraform vale sempre, e a saída obrigatória ausente, nula ou vazia dá erro.
# PASTA_DO_AMBIENTE escolhe a pasta (`infra` por padrão; a prod é `infra/ambientes/prod`). O projeto
# não vem do Terraform: com a prod, GCP_PROJECT_ID tem de vir do ambiente, para não valer o do dev.
set -euo pipefail

deploy=0
if [[ ${1-} == --deploy ]]; then
  deploy=1
  shift
fi
pasta=${PASTA_DO_AMBIENTE:-infra}
if [[ $pasta != infra && -z ${GCP_PROJECT_ID-} ]]; then
  echo "A pasta $pasta não é a do dev: defina GCP_PROJECT_ID com o projeto desse ambiente." >&2
  exit 1
fi

nomes=() saidas=() opcionais=()
for item in "$@"; do
  opcional=0
  if [[ $item == *:opcional ]]; then
    opcional=1
    item=${item%:opcional}
  fi
  nome=${item%%=*}
  if [[ $item == *=* ]]; then
    saida=${item#*=}
  else
    case $nome in
      FIRESTORE_BANCO) saida=banco_firestore ;;
      FIRESTORE_BANCO_DE_SEGURANCA) saida=banco_de_seguranca ;;
      *) saida=$(tr '[:upper:]' '[:lower:]' <<<"$nome") ;;
    esac
  fi
  # Nos alvos locais, o que já vem no ambiente da pessoa não é lido.
  if [[ $deploy == 0 && -n ${!nome-} ]]; then continue; fi
  nomes+=("$nome") saidas+=("$saida") opcionais+=("$opcional")
done
[[ ${#nomes[@]} -gt 0 ]] || exit 0

json=$(terraform -chdir="$pasta" output -json) || {
  echo "Não consegui ler os outputs do Terraform em $pasta (terraform init feito? credenciais?)." >&2
  exit 1
}
jq -e 'type == "object"' >/dev/null 2>&1 <<<"$json" || {
  echo "Os outputs do Terraform em $pasta não vieram em JSON." >&2
  exit 1
}

for i in "${!nomes[@]}"; do
  nome=${nomes[$i]} saida=${saidas[$i]}
  valor=
  presente=0
  if jq -e --arg s "$saida" 'has($s) and .[$s].value != null' >/dev/null <<<"$json"; then
    presente=1
    # Valor composto só nas saídas que o chamador usa como estruturadas (hoje, limpeza_de_imagens).
    tipo=$(jq -r --arg s "$saida" '.[$s].value | type' <<<"$json")
    if [[ ($tipo == object || $tipo == array) && $saida != limpeza_de_imagens ]]; then
      echo "O output $saida do Terraform ($pasta) é um valor composto, e o chamador espera texto." >&2
      exit 1
    fi
    # tostring preserva o `false` (o Python assume true se a variável faltar ou vier vazia).
    valor=$(jq -r --arg s "$saida" '.[$s].value | if type == "string" then . elif type == "object" or type == "array" then tojson else tostring end' <<<"$json")
  fi
  if [[ $presente == 0 || -z $valor ]]; then
    if [[ ${opcionais[$i]} == 1 ]]; then
      valor=
    elif [[ $deploy == 1 ]]; then
      echo "O output $saida do Terraform ($pasta) falta ou está vazio, e o deploy precisa dele." >&2
      exit 1
    elif [[ $nome == BUSCA_INDICES_LIGADOS ]]; then
      # Texto inválido de propósito: o código para com erro em vez de assumir true e criar índices caros.
      valor=terraform_output_falhou
    else
      echo "O output $saida do Terraform ($pasta) falta ou está vazio." >&2
      exit 1
    fi
  fi
  [[ $deploy == 1 ]] || printf 'export '
  # Aspas simples, com cada apóstrofo fechado e reaberto: vale para bash 3.2 e dash (o `sh` do make).
  printf "%s='%s'\n" "$nome" "$(printf '%s' "$valor" | sed "s/'/'\\\\''/g")"
done
