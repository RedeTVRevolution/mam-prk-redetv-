.PHONY: emitir-chave listar-chaves revogar-chave instalar verificar comparar testar-afk mesclar-afk deploy-dev criar-contas atribuir-papeis definir-aprovacao gravar-cassetes testar-na-imagem

instalar:
	uv sync --locked
	npm ci --prefix web
	git config core.hooksPath .githooks

verificar:
	scripts/checar-nomes-da-nuvem.sh
	uv run --locked ruff check
	uv run --locked ruff format --check
	uv run --locked mypy api
	uv run --locked pytest
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
	scripts/afk/testes.sh

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

# Tipos de correção que exigem aprovação de Curador (E3): make definir-aprovacao TIPOS=pessoa.renomear,pauta.titulo (vazio: nenhum)
definir-aprovacao:
	uv run --locked python -m api.definir_aprovacao "$(TIPOS)"

# Cassete do Gemini (#10): chamada real no dev sobre um clipe sintético, com as
# credenciais ADC de quem roda. Regrave a cada troca de modelo, esquema ou instrução.
# O bucket vem do Terraform (output bucket_clipes_ouro), salvo se já vier no ambiente.
gravar-cassetes:
	set -a && . ./.env && set +a && \
	BUCKET_CLIPES_OURO="$${BUCKET_CLIPES_OURO:-$$(terraform -chdir=infra output -raw bucket_clipes_ouro)}" \
	uv run --locked python -m api.cassete
