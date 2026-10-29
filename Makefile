.PHONY: instalar verificar comparar testar-afk mesclar-afk deploy-dev

instalar:
	uv sync --locked
	npm ci --prefix web
	git config core.hooksPath .githooks

verificar:
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
