.PHONY: gerar-copy-das-imagens-gpu gravar-jobs-falsos medir-jobs-falsos apagar-jobs-falsos preencher-planos-recorrentes medir-agrupamento-de-objetos verificar-api verificar-web emitir-chave registrar-webhook listar-chaves revogar-chave instalar verificar comparar testar-afk mesclar-afk deploy-dev criar-contas atribuir-papeis corrigir-estado carregar-programas carregar-marcas apagar-referencias-web gravar-cassetes gravar-cassete-da-busca testar-na-imagem criar-colecao-da-busca medir-busca medir-juncao sondar-busca reindexar copiar-para-bigquery migrar-banco-de-seguranca limpar-banco-padrao preencher-catalogo-dos-jobs preencher-filtros-da-busca gravar-mes-nos-jobs gravar-versao-nos-jobs preencher-jobs-do-painel preencher-revisao-do-painel preencher-taxa-diaria comparar-objetos medir-florence comparar-leituras passada-de-comparacao comparar-passadas reprocessar-versao tempo-de-revisao exportar-regressao importar-gabarito regressao taxa-de-correcao caos-dev carga-dev atualizar-openapi aceitar-esquemas cache-dos-quadros conferir-limpeza-de-imagens

# O ponto único que lê os outputs do Terraform (#756): scripts/ler-ambiente.sh roda
# `terraform output -json` uma vez e exporta só as variáveis pedidas, salvo as que já vierem no
# ambiente. Se a leitura falha, o alvo para com erro. PASTA_DO_AMBIENTE escolhe a pasta
# (infra por padrão; make ... PASTA_DO_AMBIENTE=infra/ambientes/prod), e com ela o projeto do
# arquivo de ambiente deixa de valer: GCP_PROJECT_ID vem do ambiente da pessoa.
# Uso na receita: $(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) comando...
LER_AMBIENTE = ambiente=$$(scripts/ler-ambiente.sh $(1)) && eval "$$ambiente" &&
ENV_LOCAL = projeto_da_pessoa="$${GCP_PROJECT_ID-}" && set -a && . ./.env && set +a && \
	{ [ "$${PASTA_DO_AMBIENTE:-infra}" = infra ] || GCP_PROJECT_ID="$$projeto_da_pessoa"; } &&

instalar:
	uv sync --locked
	npm ci --prefix web
	git config core.hooksPath .githooks

verificar: verificar-api verificar-web

# As duas metades rodam em jobs paralelos no CI. Os testes vão em vários processos
# (pytest-xdist): os que usam os emuladores criam coleção e bucket com UUID, então não
# disputam dados.
verificar-api:
	scripts/checar-nomes-da-nuvem.sh
	scripts/checar-ffmpeg.sh
	scripts/checar-fim-de-arquivo.sh
	uv run --locked ruff check
	uv run --locked ruff format --check
	uv run --locked mypy api
	uv run --locked pytest -n auto

verificar-web:
	npm run --prefix web lint
	npm run --prefix web typecheck
	npm run --prefix web test
	npm run --prefix web build

# Testes do validador com o ffmpeg da produção: dentro da imagem do Job de validação,
# com os testes montados só para leitura (o .dockerignore os deixa fora da imagem).
# Os do Job pedem os emuladores; sem FIRESTORE/STORAGE_EMULATOR_HOST, são pulados.
testar-na-imagem:
	docker build -q --target validacao -t mam-validacao:teste .
	docker run --rm --network host --user root -e TMPDIR=/tmp -e UV_LINK_MODE=copy \
		-e FIRESTORE_EMULATOR_HOST -e STORAGE_EMULATOR_HOST \
		-v "$(CURDIR)/api/tests:/app/api/tests:ro" mam-validacao:teste \
		uv run --locked pytest -q -rs -p no:cacheprovider api/tests/test_validador.py api/tests/test_validacao_job.py \
		api/tests/test_proporcao_4x3.py

# Agrupamento de objetos por tipo (#544), em decupagens locais (uma subpasta por programa):
# diagnóstico antes/depois e as amostras de precisão e cobertura para a pessoa marcar.
# make medir-agrupamento-de-objetos DECUPAGENS=<pasta> [AMOSTRA=100]
medir-agrupamento-de-objetos:
	uv run --locked python -m api.medir_agrupamento_de_objetos $(DECUPAGENS) --amostra $(or $(AMOSTRA),100)

# Aceite de tempos da E0: make comparar GABARITO=evals/gabarito DECUPAGENS=<pasta de JSONs>
comparar:
	uv run --locked python -m api.comparador $(GABARITO) $(DECUPAGENS)

testar-afk:
	shellcheck scripts/afk/*.sh
	npm ci --silent --prefix scripts/afk
	node --test scripts/afk/main.test.mts

mesclar-afk:
	scripts/afk/mesclar.sh $(BRANCH)

# Aplicação no ar no dev (#8): Terraform e imagem, pela conta mam-terraform.
deploy-dev:
	scripts/deploy-dev.sh

# Contas locais do dev (#11), depois do deploy-dev: cria e manda o link da senha.
criar-contas:
	scripts/criar-contas.sh

# Chave de API de um sistema da RedeTV (E7): make emitir-chave SISTEMA="Nome do sistema" ESCOPOS=criar,ler,cancelar
emitir-chave:
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	uv run --locked python -m api.emitir_chave "$(SISTEMA)" "$(ESCOPOS)"

# Webhook de um sistema da RedeTV (E7, #705): make registrar-webhook SISTEMA="Nome do sistema" URL=https://...
registrar-webhook:
	$(call LER_AMBIENTE,FIRESTORE_BANCO WEBHOOK_SEGREDOS) \
	uv run --locked python -m api.registrar_webhook "$(SISTEMA)" "$(URL)"

# Rotação de chaves (E7): no máximo duas ativas por sistema.
listar-chaves:
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	uv run --locked python -m api.gerir_chaves listar "$(SISTEMA)"

revogar-chave:
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	uv run --locked python -m api.gerir_chaves revogar "$(ID)"

# Papéis de uma conta (E3): make atribuir-papeis EMAIL=ana@redetv.com.br PAPEIS=editor,curador
atribuir-papeis:
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	uv run --locked python -m api.atribuir_papeis "$(EMAIL)" "$(PAPEIS)"

# Correção manual do estado de um Job (#289), com motivo e auditoria: make corrigir-estado JOB=... ESTADO=concluido|falhou MOTIVO=...
corrigir-estado:
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS FIRESTORE_BANCO_DE_SEGURANCA) \
	uv run --locked python -m api.correcao_de_estado "$(JOB)" "$(ESTADO)" "$(MOTIVO)"

# Cache-Control dos quadros já gravados (#410), o mesmo que o gravar_quadro põe nos novos
# (CACHE_DO_QUADRO, api/nuvem.py): só o metadado de <job>/quadros/*.jpg; não regrava nem apaga.
# Rodar no dev depois do deploy, e no prod quando houver. Repetir não muda nada.
cache-dos-quadros:
	$(call LER_AMBIENTE,BUCKET_DECUPAGENS) \
	gcloud storage objects update "gs://$${BUCKET_DECUPAGENS:?}/*/quadros/*.jpg" \
		--cache-control="private, max-age=86400"

# Carga única dos programas e das pessoas (#338), a partir de um TOML (padrão: docs/migracao/programas-2026-11.toml); idempotente.
carregar-programas:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.carregar_programas "$(or $(ARQUIVO),docs/migracao/programas-2026-11.toml)"

# Carga inicial do catálogo de marcas (#150), a partir dos comerciais das Decupagens; idempotente.
carregar-marcas:
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	uv run --locked python -m api.carregar_marcas

# Migração única da retirada das referências na web (#327): apaga as fotos, os rostos
# `origem=web`, as sugestões de perfil e os registros da comparação, e imprime a contagem
# antes e depois. Rodar de novo não apaga nada a mais. Depois, rode `make copiar-para-bigquery`
# e `make reindexar`: o nome que voltou a palpite ainda está no tempo de tela e na busca.
apagar-referencias-web:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_REFERENCIAS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.apagar_referencias_web

# Cassetes da busca (#507) e do Gemini (#10): chamadas reais no dev, com as
# credenciais ADC de quem roda. Regrave a cada troca de modelo, esquema ou instrução.
# O bucket vem do Terraform (output bucket_clipes_ouro), salvo se já vier no ambiente.
gravar-cassetes: gravar-cassete-da-busca
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_CLIPES_OURO) \
	uv run --locked python -m api.cassete

# Aceite dos cinco esquemas do Gemini contra o Vertex (#617): chamadas curtas de texto, só 400
# reprova. O deploy-dev já o chama; fora do `verificar` e do CI, que não têm credenciais.
aceitar-esquemas:
	set -a && . ./.env && set +a && uv run --locked python -m api.aceite_dos_esquemas

# Nomes da busca (#117): vêm do Terraform (outputs busca_*), salvo se já vierem no ambiente.
# BUSCA_INDICES_LIGADOS=false (o dev, por custo) faz a busca ir sem índice ANN e o
# criar-colecao-da-busca não criar o índice. Se o output falhar, o valor vira texto
# inválido e o código para com erro, em vez de assumir true e criar índices caros.
# BUSCA_COTA_DE_ESCRITA vazia (output ainda não aplicado) grava sem ritmo, só com a nova
# tentativa no 429 (#411).
AMBIENTE_DA_BUSCA = $(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUSCA_REGIAO BUSCA_COLECAO BUSCA_COLECAO_DE_TEXTO BUSCA_COLECAO_DE_MEDIDA BUSCA_INDICE_DESCRICAO BUSCA_INDICES_LIGADOS BUSCA_DIMENSAO BUSCA_COTA_DE_ESCRITA:opcional $(1))

# Contrato do OR entre formas (#507): chamada real, separada do cassete do Gemini.
gravar-cassete-da-busca:
	$(call AMBIENTE_DA_BUSCA,) uv run --locked python -m api.cassete busca

# Coleção de momentos e índices ANN da busca, no Agent Retrieval; idempotente.
criar-colecao-da-busca:
	$(call AMBIENTE_DA_BUSCA,) uv run --locked python -m api.criar_colecao_da_busca

# Medição da busca (#117): make medir-busca [CONSULTAS=30] [DIMENSOES="128 256"]; só com credenciais.
medir-busca:
	$(call AMBIENTE_DA_BUSCA,) uv run --locked python -m api.medir_busca $(or $(CONSULTAS),30) $(DIMENSOES)

# Sonda da busca: as consultas de api/consultas_da_sonda.toml no dev, com o corte do serviço, e um veredito por consulta.
sondar-busca:
	$(call AMBIENTE_DA_BUSCA,BUSCA_DISTANCIA_MAXIMA BUSCA_PALAVRAS_MINIMAS) \
	uv run --locked python -m api.sondar_busca

# Comparação de duas leituras da tela do mesmo vídeo (#233), sem nuvem:
# make comparar-leituras REFERENCIA=<json> NOVA=<json> [OPCOES="--lidos-nova N --segundos-nova S --segundos-referencia S"]
comparar-leituras:
	uv run --locked python -m api.comparar_leituras "$(REFERENCIA)" "$(NOVA)" $(OPCOES)

# Comparação dos motores do inventário de objetos (#244): make comparar-objetos JOB=<id> [PASTA=comparacao-objetos]
# Roda o Job do Florence-2 com o destino alternativo (a Decupagem não muda) e, aqui, a
# conversão e os modelos do Gemini; guarda por motor o inventário, os tokens, o tempo e o custo.
# MODELOS_DA_COMPARACAO e PRECOS_DOS_MODELOS (modelo=entrada:saida, US$ por milhão de tokens) vêm do ambiente.
comparar-objetos:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_DECUPAGENS REGIAO_GPU JOB_DE_OBJETOS_GPU) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.comparar_objetos "$(JOB)" "$(or $(PASTA),comparacao-objetos)"

# Medição da junção das pessoas sem nome (#547), em Decupagens baixadas: make medir-juncao ARQUIVOS="a.json b.json" [AMOSTRA=100]
medir-juncao:
	uv run --locked python -m api.medir_juncao $(ARQUIVOS) $(if $(AMOSTRA),--amostra $(AMOSTRA))

# Medição das variações do Florence-2 na GPU (#329): make medir-florence JOB=<id> [VARIACOES="guloso lote8"]
# Roda o Job com GPU uma vez por variação (a base `hoje` sempre), converte com o Gemini e guarda em
# <job>/objetos/medicao/<variacao>/ sem tocar no inventário do Job; imprime a tabela.
# MODELO_OBJETOS (no .env ou no ambiente) é o modelo do Gemini que converte o bruto: o mesmo do Job de inventário.
medir-florence:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_DECUPAGENS REGIAO_GPU JOB_DE_OBJETOS_GPU) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.medir_florence "$(JOB)" $(VARIACOES)

# Reindexa na busca (#118) a Decupagem entregue de um Job ou de todos os concluídos:
# make reindexar [JOB=<id>]. Grava só o que mudou no vídeo; repetir dá o mesmo resultado.
# Sempre indexa (os disparos pelo JOB_ID só indexam o que foi pedido, #419), mas respeita a
# vez de quem já está indexando o vídeo.
reindexar:
	$(call AMBIENTE_DA_BUSCA,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	uv run --locked python -m api.indexacao $(JOB)

# Dá `sistema` e `na_lixeira` aos objetos antigos da busca (#483): make preencher-filtros-da-busca.
# Roda no dev depois de recriar o índice com os `filterFields` novos e ANTES de publicar a busca com
# o filtro: objeto sem `na_lixeira` não casa com o filtro, e o acervo antigo some da busca.
# Idempotente e retomável (só escreve o que falta), dentro da cota de escrita (#460).
preencher-filtros-da-busca:
	$(call AMBIENTE_DA_BUSCA,) uv run --locked python -m api.preencher_filtros_da_busca

# Teste do Firestore em escala (#542), só no dev: grava Jobs falsos (id `teste_NNNNNNN`), mede as listas
# do acervo com filtros combinados e apaga tudo. Veja o docstring de api/firestore_em_escala.py.
#   make gravar-jobs-falsos N=100000 ; make medir-jobs-falsos ; make apagar-jobs-falsos
ESCALA = { [ "$${PASTA_DO_AMBIENTE:-infra}" = infra ] || { echo "Os testes de escala rodam só no dev." >&2; exit 1; }; } && \
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,FIRESTORE_BANCO) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	LISTAGEM_POR_MES="$${LISTAGEM_POR_MES:-true}" \
	uv run --locked python -m api.firestore_em_escala

gravar-jobs-falsos:
	$(ESCALA) gravar $${N:?use N=<quantos>}

medir-jobs-falsos:
	$(ESCALA) medir

apagar-jobs-falsos:
	$(ESCALA) apagar

# Agrupa os planos recorrentes (mesma câmera, mesmo enquadramento) do acervo antigo (#546):
# make preencher-planos-recorrentes [GRAVAR=1]. Usa só os quadros-chave e a Decupagem do bucket, sem
# modelo. Sem GRAVAR=1 é a prévia: mostra a contagem de planos e grupos antes e depois e não escreve
# nada. Idempotente: só regrava a Decupagem do vídeo cujo grupo mudou. Não toca o bruto nem as Correções.
preencher-planos-recorrentes:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.preencher_planos_recorrentes $(if $(GRAVAR),--gravar)

# Copia no BigQuery (#260) as decupagens dos Jobs concluídos, ou a de um Job: make copiar-para-bigquery [JOB=<id>].
# Troca as linhas do vídeo; repetir dá o mesmo resultado. Nomes vêm do Terraform, salvo se já vierem no ambiente.
copiar-para-bigquery:
	$(call AMBIENTE_DA_BUSCA,BUCKET_ACEITOS BUCKET_DECUPAGENS BIGQUERY_DATASET BIGQUERY_TABELA BIGQUERY_REGIAO) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.copiar_para_bigquery $(JOB)

# Copia papéis, chaves e auditoria do (default) para o banco de segurança (#465); não apaga a origem.
# Rodar no dev depois do terraform apply e ANTES de o deploy ligar FIRESTORE_BANCO_DE_SEGURANCA nos
# serviços (README). Repetir não duplica nada.
migrar-banco-de-seguranca:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.migrar_banco_de_seguranca

# Limpeza única (#530): as cópias antigas de papéis, chaves e auditoria no banco (default), que
# hoje vivem no banco de segurança. Só conta por padrão; para apagar: make limpar-banco-padrao ARGS=--apagar
limpar-banco-padrao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.limpar_banco_padrao $(ARGS)

# Grava em cada Job concluído quem aparece nele (#359): make preencher-catalogo-dos-jobs.
# Roda no dev depois do deploy: Job sem os campos não entra no impacto da lixeira. Repetir não muda nada.
# Também recalcula `pessoas_do_catalogo` (#478): Job sem o campo não entra no impacto da fusão e da renomeação.
# Em páginas; se um Job for apagado no meio (lixeira esvaziada), o cursor fica inválido e a passada aborta: rodar de novo.
preencher-catalogo-dos-jobs:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.preencher_catalogo_dos_jobs

# Troca `operador` por `consulta` nos papéis gravados (#664): make migrar-papel-operador.
# Irreversível. Roda em cada ambiente ANTES do deploy do código novo e de novo logo antes dele,
# sem atribuir papéis nessa janela; depois do deploy, `["operador"]` viraria sem permissão.
# Repetir não muda nada.
migrar-papel-operador:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,FIRESTORE_BANCO_DE_SEGURANCA) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.migrar_papel_operador

# Grava `mes_exibicao` nos Jobs antigos que têm data de exibição (#479): make gravar-mes-nos-jobs.
# Roda no dev depois do deploy e antes de ligar `listagem_por_mes` no Terraform: sem o campo,
# o Job some da lista por período. Repetir não muda nada.
gravar-mes-nos-jobs:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.gravar_mes_nos_jobs

# Grava `versao_pipeline` nos Jobs concluídos antigos (#494): make gravar-versao-nos-jobs.
# Roda no dev uma vez, depois do deploy: lê a versão da decupagem de cada Job sem o campo. Sem
# ela, `make reprocessar-versao` ainda abre a decupagem desses Jobs. Repetir não muda nada.
gravar-versao-nos-jobs:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.gravar_versao_nos_jobs

# Grava na tabela dos Jobs do painel (#454) os Jobs que já existem: make preencher-jobs-do-painel.
# Roda uma vez no dev depois do apply: a consulta agendada só vê os Jobs com evento de uso. Repetir
# troca as linhas pelo id e dá o mesmo resultado. Depois, confira a contagem com a da coleção `jobs`.
preencher-jobs-do-painel:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BIGQUERY_DATASET BIGQUERY_TABELA_DE_JOBS BIGQUERY_REGIAO) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.jobs_do_painel

# Grava na tabela da revisão do painel (#467) as medidas de revisão que já existem: make
# preencher-revisao-do-painel. Roda uma vez no dev depois do apply (a web só copia as medidas
# novas); repetir dá o mesmo resultado. Depois, confira a contagem com `make tempo-de-revisao`.
preencher-revisao-do-painel:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BIGQUERY_DATASET BIGQUERY_TABELA_DE_JOBS BIGQUERY_TABELA_DE_REVISAO BIGQUERY_REGIAO) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.revisao_do_painel

# Grava a contagem de itens das decupagens que ainda não a têm e refaz o último ano na tabela da
# taxa de correção por dia (#455): make preencher-taxa-diaria [DIAS=<n>]. Roda uma vez no dev depois
# do apply, e de novo depois de `make reprocessar-versao` (o reprocessamento muda dias antigos; a
# execução agendada só refaz hoje e ontem). Repetir dá o mesmo resultado.
preencher-taxa-diaria:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS BIGQUERY_DATASET BIGQUERY_TABELA_DA_TAXA BIGQUERY_REGIAO) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.taxa_diaria PREENCHER $(DIAS)

# Reprocessa o acervo de propósito (#250): make reprocessar-versao [DE=<versão ou anterior>] [LIMITE=<n>]
# Lista os Jobs concluídos de versão do pipeline anterior à atual (api/versao_pipeline.py) e o custo
# estimado (CUSTO_POR_HORA_USD, opcional). Só com CONFIRMAR=1 reprocessa, em lotes, pela análise.
reprocessar-versao:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS WORKFLOW_REGIAO WORKFLOW_VALIDACAO FIRESTORE_BANCO_DE_SEGURANCA) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	CONFIRMAR="$(CONFIRMAR)" \
	uv run --locked python -m api.reprocessar_versao "$(DE)" "$(LIMITE)"

# Passada de comparação (#247): make passada-de-comparacao JOB=<id> MODELO=<modelo do Gemini>
# Roda a análise inteira do Job concluído com outro modelo (sem escalonamento) e grava a passada
# ao lado da Decupagem, que não muda. PRECOS_DOS_MODELOS (modelo=entrada:saida, US$ por milhão
# de tokens) vem do ambiente; JANELAS_EM_PARALELO é opcional (1 por padrão).
passada-de-comparacao:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.passadas "$(JOB)" "$(MODELO)"

# Compara a decupagem do Job com uma passada (#248): make comparar-passadas JOB=<id> [PASSADA=<id>]
# ou JOBS=<id>,<id>,... (soma por requisito, última passada de cada Job; MODELO= filtra a passada).
# Grava Markdown e JSON em PASTA (comparacao-passadas). PRECOS_DOS_MODELOS, DATA_DA_TABELA_DE_PRECOS
# e, opcional, TOKENS_DO_JOB (job=entrada:saida,...) vêm do ambiente.
comparar-passadas:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.ferramentas.comparar_passadas "$(or $(JOBS),$(JOB))" "$(PASSADA)" "$(MODELO)" "$(PASTA)"

# Tempo de revisão por vídeo e por pessoa, em CSV (#251): make tempo-de-revisao [DESDE=2026-11-01]
tempo-de-revisao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.tempo_de_revisao "$(DESDE)"

# Casos de regressão das correções em vigor (#253): make exportar-regressao [PASTA=evals/regressao/casos]
exportar-regressao:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.regressao "$(PASTA)"

# Casos de regressão do gabarito de famosos em CSV (#353): make importar-gabarito [GABARITO=evals/gabarito] [PASTA=evals/regressao/casos]
importar-gabarito:
	uv run --locked python -m api.importar_gabarito "$(GABARITO)" "$(PASTA)"

# Roda uma versão do pipeline no conjunto de regressão e compara com a aprovada (#254):
# make regressao VERSAO=<versão> [RESERVADOS=1] [PASTA=regressao-da-versao] [CONFIRMAR=1]
# Sem CONFIRMAR=1 só mostra o custo estimado. Sai com código 1 se um requisito fica abaixo da meta.
# DECUPAGENS é a pasta com as decupagens de cada versão; CUSTO_POR_HORA_USD é opcional.
regressao:
	set -a && . ./.env && set +a && \
	CONFIRMAR="$(CONFIRMAR)" \
	uv run --locked python -m api.regressao_da_versao "$(VERSAO)" "$(RESERVADOS)" "$(PASTA)"

# Taxa de correção por tipo, programa e versão do pipeline, em CSV (#265):
# make taxa-de-correcao [DESDE=2026-11-01] [ATE=2026-11-30] [PROGRAMA=<nome>] (dias ISO, UTC, inclusive)
taxa-de-correcao:
	$(ENV_LOCAL) \
	$(call LER_AMBIENTE,BUCKET_ACEITOS BUCKET_DECUPAGENS) \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.taxa_de_correcao "$(DESDE)" "$(ATE)" "$(PROGRAMA)"

# Teste de caos da API no dev (#274): make caos-dev URL=https://... CHAVE_A=... CHAVE_B=... [CLIPE=arquivo.mp4]
# Com CLIPE= o clipe passa pelo pipeline inteiro (gasta Gemini e GPU); sem ele, só a API.
caos-dev:
	URL="$(URL)" CHAVE_A="$(CHAVE_A)" CHAVE_B="$(CHAVE_B)" CLIPE="$(CLIPE)" uv run --locked python -m api.caos_dev

# Carga no mam-web do dev: make carga-dev URL=https://... TOKEN=<ID token da sua sessão> [USUARIOS=200 DURACAO_S=300 RAMPA_S=30 PAUSA_S=5-15]
# Só leituras e a busca por texto (que gasta embedding e Vector Search); vários tokens separados por vírgula.
carga-dev:
	URL="$(URL)" TOKEN="$(TOKEN)" USUARIOS="$(USUARIOS)" DURACAO_S="$(DURACAO_S)" RAMPA_S="$(RAMPA_S)" PAUSA_S="$(PAUSA_S)" uv run --locked python -m api.carga_dev

# O OpenAPI dos sistemas (#277) em docs/api/openapi.json; um teste do `make verificar` confere que bate.
atualizar-openapi:
	uv run --locked python -m api.documentacao_dos_sistemas

# Simula a limpeza do Artifact Registry sem apagar nada (#456): o que seria apagado, o que fica, e
# o build em uso e o da volta marcados; sai com 1 se apagaria um deles. Pede o gcloud (só leitura)
# e o terraform init feito; usa a config gcloud do MAM (mam-dev), como o deploy-dev.
conferir-limpeza-de-imagens:
	CLOUDSDK_ACTIVE_CONFIG_NAME="$${CLOUDSDK_ACTIVE_CONFIG_NAME:-mam-dev}" uv run --locked python -m api.limpeza_de_imagens

# Reescreve no Dockerfile o COPY de api/ de cada imagem com GPU a partir do fecho de imports (#758).
gerar-copy-das-imagens-gpu:
	uv run --locked python -m scripts.copy_das_imagens_gpu
