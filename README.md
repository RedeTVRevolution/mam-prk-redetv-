# MAM RedeTV

PoC de decupagem automática com IA. O plano está em `docs/Plano_MAM.md`.

- `api/`: back em Python 3.12 com FastAPI.
- `web/`: front em React, TypeScript e Vite.

## Desenvolvimento

Instale [uv](https://docs.astral.sh/uv/), Node 22 e o [gitleaks](https://github.com/gitleaks/gitleaks):

```sh
brew install uv node@22 gitleaks
```

Depois, na raiz do repositório:

```sh
make instalar   # dependências e o hook de pre-commit com o gitleaks
make verificar  # lint, tipos, testes unitários e build; nenhuma chamada à nuvem
```

O hook de pre-commit recusa o commit se o gitleaks achar um segredo nos arquivos preparados ou se o gitleaks não estiver instalado. O CI roda `make verificar` e o gitleaks em todo PR.
