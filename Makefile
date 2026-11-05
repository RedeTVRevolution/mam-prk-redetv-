.PHONY: verificar-api verificar-web emitir-chave listar-chaves revogar-chave instalar verificar comparar testar-afk mesclar-afk deploy-dev criar-contas atribuir-papeis corrigir-estado carregar-programas carregar-marcas apagar-referencias-web gravar-cassetes testar-na-imagem criar-colecao-da-busca medir-busca sondar-busca reindexar copiar-para-bigquery comparar-objetos medir-florence comparar-leituras passada-de-comparacao comparar-passadas reprocessar-versao tempo-de-revisao exportar-regressao regressao taxa-de-correcao caos-dev atualizar-openapi

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
		uv run --locked pytest -q -rs -p no:cacheprovider api/tests/test_validador.py api/tests/test_validacao_job.py

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
	uv run --locked python -m api.emitir_chave "$(SISTEMA)" "$(ESCOPOS)"

# Rotação de chaves (E7): no máximo duas ativas por sistema.
listar-chaves:
	uv run --locked python -m api.gerir_chaves listar "$(SISTEMA)"

revogar-chave:
	uv run --locked python -m api.gerir_chaves revogar "$(ID)"

# Papéis de uma conta (E3): make atribuir-papeis EMAIL=ana@redetv.com.br PAPEIS=editor,curador
atribuir-papeis:
	uv run --locked python -m api.atribuir_papeis "$(EMAIL)" "$(PAPEIS)"

# Correção manual do estado de um Job (#289), com motivo e auditoria: make corrigir-estado JOB=... ESTADO=concluido|falhou MOTIVO=...
corrigir-estado:
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.correcao_de_estado "$(JOB)" "$(ESTADO)" "$(MOTIVO)"

# Carga única dos programas e das pessoas (#338), a partir de um TOML (ARQUIVO=docs/migracao/programas-2026-11.toml); idempotente.
carregar-programas:
	uv run --locked python -m api.carregar_programas "$(ARQUIVO)"

# Carga inicial do catálogo de marcas (#150), a partir dos comerciais das Decupagens; idempotente.
carregar-marcas:
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.carregar_marcas

# Migração única da retirada das referências na web (#327): apaga as fotos, os rostos
# `origem=web`, as sugestões de perfil e os registros da comparação, e imprime a contagem
# antes e depois. Rodar de novo não apaga nada a mais. Depois, rode `make copiar-para-bigquery`
# e `make reindexar`: o nome que voltou a palpite ainda está no tempo de tela e na busca.
apagar-referencias-web:
	BUCKET_REFERENCIAS="$${BUCKET_REFERENCIAS:-$$(terraform -chdir=infra output -raw bucket_referencias)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.apagar_referencias_web

# Cassete do Gemini (#10): chamada real no dev sobre um clipe sintético, com as
# credenciais ADC de quem roda. Regrave a cada troca de modelo, esquema ou instrução.
# O bucket vem do Terraform (output bucket_clipes_ouro), salvo se já vier no ambiente.
gravar-cassetes:
	set -a && . ./.env && set +a && \
	BUCKET_CLIPES_OURO="$${BUCKET_CLIPES_OURO:-$$(terraform -chdir=infra output -raw bucket_clipes_ouro)}" \
	uv run --locked python -m api.cassete

# Nomes da busca (#117): vêm do Terraform (outputs busca_*), salvo se já vierem no ambiente.
# BUSCA_INDICE_QUADRO vazia, no ambiente ou no output, desliga o índice do quadro-chave.
AMBIENTE_DA_BUSCA = set -a && . ./.env && set +a && \
	BUSCA_REGIAO="$${BUSCA_REGIAO:-$$(terraform -chdir=infra output -raw busca_regiao)}" \
	BUSCA_COLECAO="$${BUSCA_COLECAO:-$$(terraform -chdir=infra output -raw busca_colecao)}" \
	BUSCA_COLECAO_DE_MEDIDA="$${BUSCA_COLECAO_DE_MEDIDA:-$$(terraform -chdir=infra output -raw busca_colecao_de_medida)}" \
	BUSCA_INDICE_DESCRICAO="$${BUSCA_INDICE_DESCRICAO:-$$(terraform -chdir=infra output -raw busca_indice_descricao)}" \
	BUSCA_INDICE_QUADRO="$${BUSCA_INDICE_QUADRO-$$(terraform -chdir=infra output -raw busca_indice_quadro)}" \
	BUSCA_DIMENSAO="$${BUSCA_DIMENSAO:-$$(terraform -chdir=infra output -raw busca_dimensao)}"

# Coleção de momentos e índices ANN da busca, no Agent Retrieval; idempotente.
criar-colecao-da-busca:
	$(AMBIENTE_DA_BUSCA) uv run --locked python -m api.criar_colecao_da_busca

# Medição da busca (#117): make medir-busca [CONSULTAS=30] [DIMENSOES="128 256"]; só com credenciais.
medir-busca:
	$(AMBIENTE_DA_BUSCA) uv run --locked python -m api.medir_busca $(or $(CONSULTAS),30) $(DIMENSOES)

# Sonda da busca: as consultas de api/consultas_da_sonda.toml no dev, com o corte do serviço, e um veredito por consulta.
sondar-busca:
	$(AMBIENTE_DA_BUSCA) \
	BUSCA_DISTANCIA_MAXIMA="$${BUSCA_DISTANCIA_MAXIMA:-$$(terraform -chdir=infra output -raw busca_distancia_maxima)}" \
	BUSCA_PALAVRAS_MINIMAS="$${BUSCA_PALAVRAS_MINIMAS:-$$(terraform -chdir=infra output -raw busca_palavras_minimas)}" \
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
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	REGIAO_GPU="$${REGIAO_GPU:-$$(terraform -chdir=infra output -raw regiao_gpu)}" \
	JOB_DE_OBJETOS_GPU="$${JOB_DE_OBJETOS_GPU:-$$(terraform -chdir=infra output -raw job_de_objetos_gpu)}" \
	uv run --locked python -m api.comparar_objetos "$(JOB)" "$(or $(PASTA),comparacao-objetos)"

# Medição das variações do Florence-2 na GPU (#329): make medir-florence JOB=<id> [VARIACOES="guloso lote8"]
# Roda o Job com GPU uma vez por variação (a base `hoje` sempre), converte com o Gemini e guarda em
# <job>/objetos/medicao/<variacao>/ sem tocar no inventário do Job; imprime a tabela.
# MODELO_OBJETOS (no .env ou no ambiente) é o modelo do Gemini que converte o bruto: o mesmo do Job de inventário.
medir-florence:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	REGIAO_GPU="$${REGIAO_GPU:-$$(terraform -chdir=infra output -raw regiao_gpu)}" \
	JOB_DE_OBJETOS_GPU="$${JOB_DE_OBJETOS_GPU:-$$(terraform -chdir=infra output -raw job_de_objetos_gpu)}" \
	uv run --locked python -m api.medir_florence "$(JOB)" $(VARIACOES)

# Reindexa na busca (#118) a Decupagem entregue de um Job ou de todos os concluídos:
# make reindexar [JOB=<id>]. Apaga e regrava o vídeo; repetir dá o mesmo resultado.
reindexar:
	$(AMBIENTE_DA_BUSCA) \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.indexacao $(JOB)

# Copia no BigQuery (#260) as decupagens dos Jobs concluídos, ou a de um Job: make copiar-para-bigquery [JOB=<id>].
# Troca as linhas do vídeo; repetir dá o mesmo resultado. Nomes vêm do Terraform, salvo se já vierem no ambiente.
copiar-para-bigquery:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	BIGQUERY_DATASET="$${BIGQUERY_DATASET:-$$(terraform -chdir=infra output -raw bigquery_dataset)}" \
	BIGQUERY_TABELA="$${BIGQUERY_TABELA:-$$(terraform -chdir=infra output -raw bigquery_tabela)}" \
	BIGQUERY_REGIAO="$${BIGQUERY_REGIAO:-$$(terraform -chdir=infra output -raw bigquery_regiao)}" \
	uv run --locked python -m api.copiar_para_bigquery $(JOB)

# Reprocessa o acervo de propósito (#250): make reprocessar-versao [DE=<versão ou anterior>] [LIMITE=<n>]
# Lista os Jobs concluídos de versão do pipeline anterior à atual (api/versao_pipeline.py) e o custo
# estimado (CUSTO_POR_HORA_USD, opcional). Só com CONFIRMAR=1 reprocessa, em lotes, pela análise.
reprocessar-versao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	WORKFLOW_REGIAO="$${WORKFLOW_REGIAO:-$$(terraform -chdir=infra output -raw workflow_regiao)}" \
	WORKFLOW_VALIDACAO="$${WORKFLOW_VALIDACAO:-$$(terraform -chdir=infra output -raw workflow_validacao)}" \
	CONFIRMAR="$(CONFIRMAR)" \
	uv run --locked python -m api.reprocessar_versao "$(DE)" "$(LIMITE)"

# Passada de comparação (#247): make passada-de-comparacao JOB=<id> MODELO=<modelo do Gemini>
# Roda a análise inteira do Job concluído com outro modelo (sem escalonamento) e grava a passada
# ao lado da Decupagem, que não muda. PRECOS_DOS_MODELOS (modelo=entrada:saida, US$ por milhão
# de tokens) vem do ambiente; JANELAS_EM_PARALELO é opcional (1 por padrão).
passada-de-comparacao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.passadas "$(JOB)" "$(MODELO)"

# Compara a decupagem do Job com uma passada (#248): make comparar-passadas JOB=<id> [PASSADA=<id>]
# ou JOBS=<id>,<id>,... (soma por requisito, última passada de cada Job; MODELO= filtra a passada).
# Grava Markdown e JSON em PASTA (comparacao-passadas). PRECOS_DOS_MODELOS, DATA_DA_TABELA_DE_PRECOS
# e, opcional, TOKENS_DO_JOB (job=entrada:saida,...) vêm do ambiente.
comparar-passadas:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.comparar_passadas "$(or $(JOBS),$(JOB))" "$(PASSADA)" "$(MODELO)" "$(PASTA)"

# Tempo de revisão por vídeo e por pessoa, em CSV (#251): make tempo-de-revisao [DESDE=2026-11-01]
tempo-de-revisao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	uv run --locked python -m api.tempo_de_revisao "$(DESDE)"

# Casos de regressão das correções em vigor (#253): make exportar-regressao [PASTA=evals/regressao/casos]
exportar-regressao:
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.regressao "$(PASTA)"

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
	set -a && . ./.env && set +a && \
	GCP_PROJECT_ID="$${GCP_PROJECT_ID:?}" \
	BUCKET_ACEITOS="$${BUCKET_ACEITOS:-$$(terraform -chdir=infra output -raw bucket_aceitos)}" \
	BUCKET_DECUPAGENS="$${BUCKET_DECUPAGENS:-$$(terraform -chdir=infra output -raw bucket_decupagens)}" \
	uv run --locked python -m api.taxa_de_correcao "$(DESDE)" "$(ATE)" "$(PROGRAMA)"

# Teste de caos da API no dev (#274): make caos-dev URL=https://... CHAVE_A=... CHAVE_B=... [CLIPE=arquivo.mp4]
# Com CLIPE= o clipe passa pelo pipeline inteiro (gasta Gemini e GPU); sem ele, só a API.
caos-dev:
	URL="$(URL)" CHAVE_A="$(CHAVE_A)" CHAVE_B="$(CHAVE_B)" CLIPE="$(CLIPE)" uv run --locked python -m api.caos_dev

# O OpenAPI dos sistemas (#277) em docs/api/openapi.json; um teste do `make verificar` confere que bate.
atualizar-openapi:
	uv run --locked python -m api.documentacao_dos_sistemas
