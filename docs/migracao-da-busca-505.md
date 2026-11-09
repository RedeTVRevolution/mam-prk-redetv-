# Implantação e migração das duas coleções (#505)

Execução **humana**, no dev, com ADC e o `.env` configurados. Os comandos abaixo
não foram executados pelo agente. O teste inicial da coleção sem vetor já passou
em 8/11/2026: criação em cerca de 4 s e escrita/busca por palavra com HTTP 200.
Não é necessário repetir esse experimento. Nenhum papel IAM novo é necessário.

## 1. Antes do merge e do deploy

A coleção de texto precisa existir antes do código novo entrar no ar. Para guardar
o "antes", rode o código da integração que originou este PR: a sonda nova verifica
as duas coleções e falha enquanto a de texto não existir. Este worktree separado
não troca a branch do PR. A integração contém #496, #502, #504 e #507.

```bash
RAIZ=$(git rev-parse --show-toplevel)
PASTA_505=$(mktemp -d "${TMPDIR:-/tmp}/mam-505.XXXXXX")
ANTES="$PASTA_505/antes"
git worktree add --detach "$ANTES" f14eb219564ab6134f70bffba8f7912e9f607553
ln -s "$RAIZ/.env" "$ANTES/.env"
ln -s "$RAIZ/infra/.terraform" "$ANTES/infra/.terraform"
(cd "$ANTES" && make sondar-busca) 2>&1 | tee "$PASTA_505/sonda-antes.txt"
```

Para medir a consulta livre no adaptador, salve este script fora dos dois worktrees.
Ele só lê: texto e significado, **sem tipo**, mesmas configurações e termo antes e
depois, uma chamada de aquecimento e 30 medidas. Mede a ida ao índice, incluindo o
embedding no KNN; não inclui entendimento do Gemini, Ranking API ou montagem da
resposta HTTP. `make medir-busca` mede só planos e não substitui esta medição das
duas coleções. Não altere o acervo entre a medida final e a comparação.

```bash
cat > "$PASTA_505/medir-livre.py" <<'PY'
import json
import os
import subprocess
from time import perf_counter

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.indice_da_busca import Consulta, Filtros
from api.medir_busca import percentil

outputs = json.loads(subprocess.check_output([
    "terraform", "-chdir=infra", "output", "-json"
]))
for env, output in {
    "BUSCA_REGIAO": "busca_regiao",
    "BUSCA_COLECAO": "busca_colecao",
    "BUSCA_COLECAO_DE_TEXTO": "busca_colecao_de_texto",
    "BUSCA_INDICE_DESCRICAO": "busca_indice_descricao",
    "BUSCA_DIMENSAO": "busca_dimensao",
    "BUSCA_INDICES_LIGADOS": "busca_indices_ligados",
    "BUSCA_DISTANCIA_MAXIMA": "busca_distancia_maxima",
    "BUSCA_PALAVRAS_MINIMAS": "busca_palavras_minimas",
}.items():
    if output in outputs:
        os.environ.setdefault(env, str(outputs[output]["value"]).lower())
indice = AgentRetrieval(ConfigDaBusca.do_ambiente(os.environ), transporte_http())
consulta = Consulta(texto="terno", significado="terno", limite=500,
                    cortar_significado=True, filtros=Filtros(na_lixeira=False))
indice.buscar(consulta)
tempos = []
for _ in range(30):
    inicio = perf_counter()
    achados = indice.buscar(consulta)
    tempos.append(perf_counter() - inicio)
print(json.dumps({"consulta": "terno", "n": 30, "registros": len(achados),
                  "p50_ms": 1000 * percentil(tempos, 50),
                  "p95_ms": 1000 * percentil(tempos, 95)}))
PY
(cd "$ANTES" && set -a && . ./.env && set +a && \
  PYTHONPATH="$ANTES" uv run --locked python "$PASTA_505/medir-livre.py") \
  | tee "$PASTA_505/latencia-antes.json"
```

Agora, na raiz do **worktree do PR**, confira o plano: só as três variáveis de
ambiente e os outputs novos, nenhuma remoção ou recriação de recurso. O refresh
publica o output sem implantar o código nem as variáveis no Cloud Run.

```bash
cd "$RAIZ"
terraform -chdir=infra plan
terraform -chdir=infra apply -refresh-only
make criar-colecao-da-busca
set -a
. ./.env
set +a
export BUSCA_REGIAO="$(terraform -chdir=infra output -raw busca_regiao)"
export BUSCA_COLECAO="$(terraform -chdir=infra output -raw busca_colecao)"
export BUSCA_COLECAO_DE_TEXTO="$(terraform -chdir=infra output -raw busca_colecao_de_texto)"
BASE_DA_BUSCA="https://vectorsearch.googleapis.com/v1beta/projects/$GCP_PROJECT_ID/locations/$BUSCA_REGIAO/collections"
```

Confira o esquema sem vetor e a ausência de índice da coleção nova:

```bash
curl --fail-with-body -sS -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  "$BASE_DA_BUSCA/$BUSCA_COLECAO_DE_TEXTO" \
  | jq -e '(.vectorSchema // {} | length) == 0 and (.dataSchema.properties | has("significado") | not)'
curl --fail-with-body -sS -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  "$BASE_DA_BUSCA/$BUSCA_COLECAO_DE_TEXTO/indexes" | jq -e '(.indexes // [] | length) == 0'
JOB_TESTE='<id de um vídeo de teste concluído>'
make reindexar JOB="$JOB_TESTE"
```

Conte os quatro tipos **nas duas coleções**, filtrando o vídeo. O aggregate aceita
`COUNT` e filtro; por isso é uma chamada por tipo, sem presumir `groupBy`
([referência da API](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search-2/reference/rest/v1/projects.locations.collections.dataObjects/aggregate)).
Defina a função uma vez nesta sessão:

```bash
contar_tipos() {
  for colecao in "$BUSCA_COLECAO" "$BUSCA_COLECAO_DE_TEXTO"; do
    for tipo in plano fala texto_na_tela objeto; do
      corpo=$(jq -nc --arg tipo "$tipo" --arg job "${1:-}" \
        '{aggregate:"COUNT",filter:{"$and":([{tipo:{"$eq":$tipo}}] + (if $job == "" then [] else [{job_id:{"$eq":$job}}] end))}}')
      printf '%s %s ' "$colecao" "$tipo"
      curl --fail-with-body -sS -X POST \
        -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
        -H 'Content-Type: application/json' -d "$corpo" \
        "$BASE_DA_BUSCA/$colecao/dataObjects:aggregate" | jq '[.aggregateResults[]?.count | tonumber] | add // 0'
    done
  done
}
contar_tipos "$JOB_TESTE" | tee "$PASTA_505/contagens-video.txt"
```

Esperado: no vídeo, só planos na coleção vetorial; só os outros três tipos na de
texto (um tipo ausente na decupagem pode ter zero). Até o deploy, fala, GC e objeto
desse vídeo somem da busca antiga. Isso é aceitável no dev.

## 2. Merge e deploy

Só depois da validação acima e do CI verde. O deploy deve aplicar as variáveis
novas na web, na indexação e na purga. Entre o deploy e a reindexação geral, a busca
por fala, GC e objeto fica incompleta; a busca sem tipo ainda pode achar registros
antigos na coleção vetorial. Essa janela é aceita no dev.

## 3. Reindexação geral

No worktree com o código novo e o ambiente acima:

```bash
make reindexar
```

Isso move os vídeos concluídos fora da lixeira. A comparação por coleção remove
o que deixou de ser plano da coleção vetorial e cria o correspondente na de texto.
Cada registro movido custa duas escritas, uma na cota de cada coleção. Repetir é
idempotente e uma queda pode ser retomada.

## 4. Concluídos na lixeira, por ids explícitos

Sem `JOB`, o comando anterior **só marca** os registros desses vídeos como
`na_lixeira`; não os migra. Liste os ids pelo repositório de Jobs (só leitura,
banco padrão do Firestore), revise a lista e passe os ids explicitamente:

```bash
uv run --locked python - <<'PY' | tee "$PASTA_505/concluidos-na-lixeira.txt"
import os
from google.cloud import firestore
from api.nuvem import RepositorioFirestore

jobs = RepositorioFirestore(firestore.Client(project=os.environ["GCP_PROJECT_ID"]))
for job in jobs.listar():
    if job.estado == "concluido" and job.lixeira is not None:
        print(job.id)
PY
IDS_NA_LIXEIRA=$(tr '\n' ' ' < "$PASTA_505/concluidos-na-lixeira.txt")
if [ -n "$IDS_NA_LIXEIRA" ]; then
  make reindexar JOB="$IDS_NA_LIXEIRA"
fi
```

A guarda evita executar a reindexação geral se a lista estiver vazia. Esse caminho
reindexa sem restaurar o vídeo e mantém `na_lixeira=True` nas duas coleções,
coberto por teste. A cópia do BigQuery continua recebendo todos os registros.

## 5. Depois da migração e evidências no PR

```bash
contar_tipos | tee "$PASTA_505/contagens-totais-depois.txt"
make sondar-busca 2>&1 | tee "$PASTA_505/sonda-depois.txt"
PYTHONPATH="$RAIZ" uv run --locked python "$PASTA_505/medir-livre.py" \
  | tee "$PASTA_505/latencia-depois.json"
```

A contagem da coleção vetorial inteira deve ter zero fala, GC e objeto, **incluindo
os vídeos na lixeira**. Registre no PR as contagens, as duas sondas, cada consulta
que piorou e o motivo, e os p50/p95 abaixo. Não substitua resultados ausentes por
estimativas ou pelas medidas históricas da ADR 0006.

| Evidência | Antes | Depois |
|---|---|---|
| Sonda e explicação de cada piora | Pendente: humano | Pendente: humano |
| Busca livre, p50/p95 (ms) | Pendente: humano | Pendente: humano |
| Contagem por tipo nas duas coleções | Vídeo de teste: pendente | Acervo inteiro: pendente |
| Plan Terraform sem destruição | Pendente: humano | — |

Com poucos milhares de registros, a latência do dev não prova desempenho em
escala. `textSearch` sem índice com milhões de registros continua sem medição.
O worktree anterior pode ser removido com `git worktree remove "$ANTES"`; preserve
os relatórios de `$PASTA_505` para anexar os resultados ao PR.

Não apague coleções para esta migração. Para qualquer remoção futura, esvazie os
objetos antes: o DELETE com objetos retorna `COLLECTION_HAS_DATA_OBJECTS`, mesmo
com `force=true`. `apagar_colecao` já faz a limpeza antes de remover a coleção
vetorial temporária da medição.

## Rollback

Antes de voltar à imagem anterior, suspenda a purga: ela apaga só da `momentos` e
remove o Job, deixando falas, GC e objetos órfãos na coleção de texto. No worktree
novo, com o ambiente da seção 1, esvazie **só a coleção de texto**, reutilizando a
remoção em lotes existente (a coleção permanece):

```bash
BUSCA_INDICE_DESCRICAO="$(terraform -chdir=infra output -raw busca_indice_descricao)" \
BUSCA_DIMENSAO="$(terraform -chdir=infra output -raw busca_dimensao)" \
uv run --locked python - <<'PY'
import os
from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, OBJETOS_POR_PAGINA, transporte_http

config = ConfigDaBusca.do_ambiente(os.environ)
colecao = os.environ["BUSCA_COLECAO_DE_TEXTO"]
indice = AgentRetrieval(config, transporte_http(), tentar_no_429=True)
nomes = []
pedido = {"pageSize": OBJETOS_POR_PAGINA}
while True:
    pagina = indice._chamar("dataObjects:query", pedido, esperar=True, colecao=colecao)
    nomes.extend(o["name"] for o in pagina.get("dataObjects", []))
    if not pagina.get("nextPageToken"):
        break
    pedido = pedido | {"pageToken": pagina["nextPageToken"]}
indice._apagar_nomes(nomes, colecao)
PY
```

Reindexe com a imagem/código anterior (`cd "$ANTES" && make reindexar`), incluindo
os ids na lixeira como na seção 4: os registros voltam para a `momentos`. Só retome
a purga após concluir a limpeza da coleção de texto.
