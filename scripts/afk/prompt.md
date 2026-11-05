# Loop AFK: implementar um ticket

Você trabalha sozinho, sem ninguém olhando, e ninguém responde perguntas durante a execução: não pergunte nada no chat. O ticket desta iteração está no fim deste texto, em **Esta iteração**. Trabalhe só nele.

## Antes de começar

1. Leia `AGENTS.md`, `GLOSSARY.md` e os ADRs de `docs/adr/` que tocam o ticket.
2. Leia o ticket com os comentários: `gh issue view <N> --comments`. Leia também a spec indicada em "Parte de" (por exemplo `gh issue view 1`): os pontos de teste combinados estão no ticket e na spec.
3. Leia `.afk/progresso.md`. Se esta iteração continua o ticket, leia também o `git log` indicado em **Esta iteração** e retome de onde parou.

## Passos

Chame a skill pela ferramenta Skill, com o nome completo. Se ela não estiver disponível, não use outra no lugar: anote em `.afk/progresso.md` que a skill faltou e termine com o status `erro`.

1. Implemente com a skill `mattpocock-skills:tdd`, nos pontos de teste combinados no ticket e na spec.
2. Rode `make verificar` até passar.
3. Faça commit. A mensagem começa com `#<N>: `.

Não revise o próprio trabalho: quando você termina com `feito`, o script abre outro agente, com contexto novo, que revisa o ticket inteiro e commita as correções.

## Quando precisar de uma decisão humana

Se não der para seguir sem uma decisão de pessoa (requisito ambíguo, conflito com um ADR, algo que exige nuvem ou credencial):

1. Comente a pergunta no ticket com `gh issue comment <N> --body "..."`: o que está em dúvida, as opções e qual você recomenda.
2. Troque a label: `gh issue edit <N> --remove-label ready-for-agent --add-label ready-for-human`.
3. Termine com o status `bloqueado`. O script guarda o trabalho parcial num branch local e segue para o próximo ticket.

## Aviso de contexto

Se um hook avisar que o contexto passou do limite, siga o aviso na hora: comite só o que está verde, anote o que falta e termine com o status `parcial`. A próxima iteração continua o ticket com o contexto vazio.

## Regras

- Não faça push, não troque de branch e não reescreva commits que você não fez nesta iteração.
- Não use `git worktree` nem `git stash`: outros agentes trabalham ao mesmo tempo no mesmo repositório, e os dois mexem no que é de todos.
- Não feche issues e não ponha a label `afk-feito`: o script faz isso depois de conferir `make verificar`.
- Não edite `scripts/afk/` nem `.claude/`.
- Não há credencial de nuvem aqui. Nada de `gcloud`, `terraform apply` ou chamadas reais ao Gemini: os testes usam versões falsas.
- No fim da iteração, o script descarta o que não estiver commitado, roda a revisão (se você terminou com `feito`) e depois `make verificar`. Se falhar, ele desfaz todos os commits da iteração.

## Notas para a próxima iteração

Antes de terminar, acrescente ao fim de `.afk/progresso.md`, sem apagar o que já está lá, poucas linhas: o ticket, o que ficou pronto, o que falta, as decisões tomadas e as armadilhas encontradas.

Cada iteração roda num contêiner novo, e só os commits e o `.afk/progresso.md` passam para a próxima: qualquer outro arquivo some, inclusive em `.afk/` (um patch, um rascunho). Divida o trabalho em partes que passam no `make verificar` e comite cada parte pronta; o que não estiver num commit, a próxima iteração refaz.

## Fim da resposta

Termine a resposta com estas duas linhas:

```
<ticket>N</ticket>
<status>feito|parcial|bloqueado|erro</status>
```

- `feito`: ticket completo e commitado, `make verificar` verde. A revisão vem em seguida, com outro agente.
- `parcial`: falta trabalho, e o que está commitado passa no `make verificar`. A próxima iteração continua.
- `bloqueado`: você comentou a pergunta no ticket e trocou a label.
- `erro`: problema do ambiente (skill ausente, ferramenta quebrada), não do ticket. O loop para.
