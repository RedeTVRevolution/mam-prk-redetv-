# Não dividir o `api/nuvem.py` em pacote

O `api/nuvem.py` reúne os adapters do Google Cloud (Storage, Firestore, BigQuery, Pub/Sub e outros). É grande, mas continua um módulo só.

**Decisão de 13/11/2026 — Bruno:** não transformar o `nuvem.py` num pacote `api/nuvem/`. O custo é alto e o ganho é pequeno:

- 42 módulos de produção e 15 de teste importam `api.nuvem`;
- 12 monkeypatches nos testes apontam para `"api.nuvem.…"` por string, e quebrariam sem erro de importação;
- o analisador de `api/tests/test_imagens_gpu.py` lê cada módulo como `api/<modulo>.py` para montar o fecho de imports das imagens de GPU, então pressupõe módulos planos.

Extrair do `nuvem.py` um módulo plano e isolado continua permitido quando há ganho medido, como o de clientes de nuvem (sessão autenticada e transporte REST). O módulo novo entra nas listas de GPU do Dockerfile que precisarem dele. O Storage dos Jobs foi medido e ficou de fora: o Storage de objetos depende da contagem de itens (Correções) e da contagem de arquivos (lixeira, que importa Jobs), e o fecho do `objetos-gpu` cairia só de cerca de 50 para cerca de 40 módulos.
