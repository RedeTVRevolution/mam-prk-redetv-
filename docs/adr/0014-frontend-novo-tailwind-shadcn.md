> **As sugestões saíram** em 6/11/2026 (decisão do Bruno, #487): identificar pessoa, pauta do trecho e objeto do visual, com as rotas, o painel e a contagem. O item "sugestões" da lista abaixo não será migrado.

# Frontend novo: Tailwind e shadcn no lugar do Mantine, trocado por fases

Em 5/11/2026, o Bruno aprovou o protótipo do redesenho (`prototipos/redesenho`, opção B Galeria) para virar o `web/` de produção. Ele também decidiu:
- migrar todas as funções do `web/` atual, inclusive as que o protótipo não desenhou (sugestões, renomeação em lote, fusão de pessoa, comparação de passadas, juntar e dividir pautas, planos parecidos, fila e aprovação do Curador, trecho com entrada e saída, modo de catalogação);
- entregar em PRs por fase, cada um com o CI verde. Quem mescla é ele.

O design vale pelo `docs/design/MAM_DESIGN_SYSTEM.md`. O plano das fases está em `docs/design/plano-da-migracao-do-web.md`.

## Decisões

**Pilha.** Tailwind v4 e componentes shadcn/ui (Radix), ícones Tabler, TanStack Query para os dados da API, TanStack Virtual para as listas longas, Recharts nos gráficos (já usado hoje), sonner nos avisos e cmdk na busca global. O Mantine sai na última fase.

**Os dois frontends convivem no mesmo `web/` até a troca.** O `main.tsx` escolhe a interface e carrega só ela, por `import()` dinâmico:
- o padrão continua sendo a interface atual;
- `?interface=nova` liga a nova e fica guardado no navegador; `?interface=atual` volta.

Cada interface traz o próprio CSS no próprio pedaço do build. Assim o reset do Tailwind nunca encontra o CSS do Mantine na mesma página. As URLs, a API, o login e o deploy não mudam. Na última fase a nova vira o padrão, e a atual e o Mantine são apagados.

*Atualização de 6/11/2026 (fase 7, feita):* a escolha por `?interface=` deixou de existir. O `main.tsx` carrega só a interface nova, e a atual, o Mantine, a `/amostra` e os testes das telas antigas foram apagados.

**Reaproveitar a camada de dados.** A interface nova usa o mesmo `api.ts`, o mesmo `auth/`, o mesmo `rotas.ts` (History API, com os mesmos endereços: um link já mandado continua abrindo) e os módulos de regra (`catalogacao.ts`, `pautas.ts`, `timecode.ts`, `linhaDoTempo.ts` e outros), com os testes deles. Só a camada de tela é nova, em `web/src/novo/`.

**Memória e CPU.** São regras para toda tela nova:
- lista que pode passar de 200 itens é virtual e paginada, com teto de páginas na memória (`maxPages`). Exemplo: o acervo guarda 6 páginas de 50;
- a consulta que sai da tela é descartada (`gcTime`), e a consulta de outro filtro sai na hora;
- o navegador nunca soma dado cru. Gráfico recebe no máximo ~90 pontos, já somados pelo servidor, e ranking recebe os N primeiros com cursor;
- imagem só é pedida quando entra na tela.

**Relatórios no servidor.** O Tempo de tela e Marcas passam a devolver:
- os N primeiros, com cursor para "ver mais";
- o detalhe por vídeo só quando a pessoa ou a marca é aberta, em vez de tudo na mesma resposta.

Gráfico no tempo agrupa por dia, semana, mês ou trimestre, conforme o período, e a API recusa pedido que gere mais pontos que o teto. As consultas continuam nas tabelas e somas que já existem no BigQuery. Nenhuma tabela nova é criada, e o `infra/` não muda.

**Cache de imagens.** Os quadros e o proxy chegam por URL assinada, e uma assinatura nova a cada pedido impede qualquer cache. A mudança vai numa fase própria, com ticket:
- assinar com validade arredondada, para a URL ser a mesma dentro da janela;
- gravar `Cache-Control` nos objetos;
- no service worker, usar uma chave sem os parâmetros da assinatura e limpar o cache no logout.

**Testes de estilo.** As regras do `estilo.test.ts` continuam para as duas interfaces: sem gradiente, sem sombra com desfoque acima de 8 px e sem emoji. Os componentes shadcn são ajustados para cumpri-las. O `tema.test.ts` ganha a versão sobre os tokens CSS da interface nova: contraste AA, as 7 cores de tipo distinguíveis também em deuteranopia, e o "Decupando" em âmbar.

## Por quê

- Trocar 18 mil linhas de uma vez quebraria a suíte inteira e deixaria a `main` vermelha por semanas. O ruleset não deixa mesclar assim.
- Com as duas interfaces na mesma aplicação, cada fase vai ao ar sem mexer no que os usuários usam, e dá para testar a nova no dev com dados reais antes da troca.
- O Mantine e o Tailwind na mesma página brigam pelo reset do CSS. O `import()` dinâmico separa os dois sem precisar de um segundo build, de outra rota no FastAPI ou de outro serviço.
- No `web/` atual, os relatórios devolvem tudo: todas as pessoas com todos os vídeos, e cada inserção de marca. Com 25 anos de acervo, isso lota a instância e o navegador. Cortar no servidor é o que limita os dois.
