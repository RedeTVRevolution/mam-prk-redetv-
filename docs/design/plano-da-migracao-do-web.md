# Plano da migração do `web/` para a interface nova

Decisão no ADR 0014 (5/11/2026). Origem: o protótipo `prototipos/redesenho`, opção B Galeria, aprovado pelo Bruno. O design segue o `docs/design/MAM_DESIGN_SYSTEM.md`.

## Como cada fase é feita

- Um PR por fase, a partir da `main`, com o CI verde. Quem mescla é o Bruno.
- A interface nova fica em `web/src/novo/` e é ligada com `?interface=nova`. A atual continua sendo o padrão até a fase 7 (feita: `?interface=` não existe mais).
- Toda tela é testada em 1280, 1024 e 390 px. Toda lista longa tem a memória medida no build de produção, com a CPU 4× mais lenta. A meta é menos de 200 MB, menos de 3 mil elementos na página e nenhuma tarefa acima de 200 ms.
- Todo código novo ou alterado passa por revisão independente antes do push.
- Os testes da tela são vitest, com testing-library e msw, como os de hoje. A regra de cada tela antiga que já tem teste ganha o mesmo teste na nova.

## Fases

**1. Base.**
- Tailwind v4, shadcn e os tokens do design system em `web/src/novo/`.
- A escolha da interface no `main.tsx`.
- A casca (barra lateral, busca global, atalhos) e o login com verificação em duas etapas, inclusive o cadastro do TOTP, reaproveitando o `auth/`.
- O TanStack Query sobre o `api.ts`.
- O `tema.test.ts` sobre os tokens novos, e o `estilo.test.ts` valendo para as duas interfaces.

**2. Acervo e vídeo.**
- O acervo em grade e lista virtual: a `AcervoB` do protótipo, com a API real.
- O envio.
- O player com `<video>` de verdade, linha do tempo e inspetor.
- Correção e acréscimo de itens, reprocessar e lixeira.
- O teto de páginas na memória funciona nos dois sentidos sem mudar a API: o navegador guarda o cursor de cada página por onde já passou (uns 100 bytes por página) e volta com ele.
- Tickets: #347, #350.

**3. Busca e relatórios.**
- A busca em mosaico na grade (#400), com cursor (#426; para trás, o navegador guarda os cursores, como no acervo) e o aviso de vídeos ainda entrando (#404).
- A busca por imagem e os planos parecidos (os parecidos saíram no #476).
- Tempo de tela e Marcas. Backend: os N primeiros com cursor e o detalhe por vídeo só quando aberto.

**4. Painel e Administração.**
- As 6 abas do Painel da diretoria. Backend: os gráficos no tempo agrupados por dia, semana, mês ou trimestre, conforme o período, com teto de pontos.
- A fila de processamento no Painel e a remoção do `mam-fila` (#420; a pausa no Terraform é o #421).
- As 7 abas da Administração (#348, #401), com a foto da pessoa em Programas (#403).

**5. Curadoria.**
- Sugestões, renomeação em lote, fusão de pessoa, comparação de passadas, juntar e dividir pautas.
- Fila e aprovação do Curador, trecho com entrada e saída, e o modo de catalogação.
- O pulso da sessão de revisão.

**6. Cache de imagens.** Depois dos #408, #409 e #410 (capas com URL estável e `Cache-Control`), o service worker guarda os quadros com uma chave sem a assinatura e limpa o cache no logout.
- Feito: `web/src/sw.ts` (publicado em `/sw.js`, escopo `/`, sem dependência nova) guarda só o GET de `<img>` para URL assinada do Storage, com chave sem os `X-Goog-*`, teto de 500 imagens de até 1 MB e vida de 1 dia (a do `Cache-Control`). As regras e os testes estão em `web/src/cacheDeImagens.ts`; o `sair` da sessão, comum às duas interfaces, apaga o cache.
- O worker refaz o pedido em modo `cors` para conferir status e tipo antes de guardar (uma resposta opaca esconderia um 403). Por isso o bucket `decupagens` ganha CORS de GET no Terraform, que o Bruno aplica. Sem ele o worker anota a recusa por 1 h e as imagens seguem pela rede, como antes.

**7. Troca.**
- A interface nova vira o padrão.
- A atual, o Mantine, a `/amostra` e os testes das telas antigas são apagados.
- O `make verificar` e o `checar-nomes-da-nuvem.sh` passam a olhar só a nova.
- Feito: o `main.tsx` carrega só a nova (`web/src/novo/`, sem `?interface=`); as telas da atual, os testes delas, a `/amostra`, o `interface.ts` e o `tema.ts` foram apagados (80 arquivos, uns 23 mil linhas); `@mantine/charts`, `@mantine/core` e `@mantine/hooks` saíram do `package.json`. Ficam, compartilhados, o `api.ts`, o `rotas.ts`, o `sessao.ts`, o `cacheDeImagens.ts` e os módulos de regra com os testes deles. O `checar-nomes-da-nuvem.sh` e o `make verificar-web` não mudaram de comando: como a atual saiu de `web/src/`, eles já olham só a nova.
- Antes de apagar, o inventário de paridade achou três funções que só a atual tinha, e elas foram para a nova: o vídeo aberto pela busca (faixa Busca, N, Shift+N e Fechar busca), o botão "Planos parecidos com este" (removido no #476) e a seção Planos do inspetor (por onde se corrige a descrição e o plano limpo).
- Sugestão, não feita: mover `web/src/novo/` para `web/src/` (o nome `novo` ficou sem sentido). É um diff gigante sem ganho funcional; vale como PR à parte, só de `git mv`.

## Fora deste plano

O protótipo continua em `prototipos/redesenho`, fora do Git. Os quadros reais em `public/m` nunca entram no repositório.
