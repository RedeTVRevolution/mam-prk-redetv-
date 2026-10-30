.PHONY: instalar verificar comparar testar-afk mesclar-afk deploy-dev criar-contas gravar-cassetes

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

# Cassete do Gemini (#10): chamada real no dev sobre um clipe sintético, com as
# credenciais ADC de quem roda. Regrave a cada troca de modelo, esquema ou instrução.
# O bucket vem do Terraform (output bucket_clipes_ouro), salvo se já vier no ambiente.
gravar-cassetes:
	set -a && . ./.env && set +a && \
	BUCKET_CLIPES_OURO="$${BUCKET_CLIPES_OURO:-$$(terraform -chdir=infra output -raw bucket_clipes_ouro)}" \
	uv run --locked python -m api.cassete
