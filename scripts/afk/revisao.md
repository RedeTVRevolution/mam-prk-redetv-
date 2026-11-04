# Loop AFK: revisar um ticket

Você trabalha sozinho, sem ninguém olhando, e ninguém responde perguntas durante a execução: não pergunte nada no chat. Outro agente acabou de implementar e commitar o ticket indicado no fim deste texto, em **Esta iteração**. Você não viu esse trabalho sendo feito: revise o que está commitado.

## Antes de começar

1. Leia `AGENTS.md` e `GLOSSARY.md`.
2. Leia o ticket com os comentários: `gh issue view <N> --comments`, e a spec indicada em "Parte de" (por exemplo `gh issue view 1`).

## Passos

Chame a skill pela ferramenta Skill, com o nome completo. Se ela não estiver disponível, não use outra no lugar (nem o `/code-review` embutido): anote em `.afk/progresso.md` que a skill faltou e termine com `erro`.

1. Revise com a skill `mattpocock-skills:code-review`, passando como ponto fixo o commit de antes do ticket indicado em **Esta iteração** e o ticket como spec.
2. Corrija o que a revisão apontar, rode `make verificar` até passar e faça um commit novo. A mensagem começa com `#<N>: revisão: `.
3. Se decidir não corrigir algum ponto, ou se ele precisar de uma decisão humana, anote em `.afk/progresso.md` o ponto e o motivo. Se não houver nada a corrigir, não faça commit.

## Regras

- Só commits novos: não use `--amend`, rebase nem reset nos commits que já estão no branch.
- Não faça push e não troque de branch.
- Não use `git worktree` nem `git stash`: outros agentes trabalham ao mesmo tempo no mesmo repositório, e os dois mexem no que é de todos.
- Não comente nem edite issues e não mexa em labels: o script cuida disso.
- Não edite `scripts/afk/` nem `.claude/`.
- Não há credencial de nuvem aqui. Nada de `gcloud`, `terraform apply` ou chamadas reais ao Gemini.
- No fim, o script descarta o que não estiver commitado e roda `make verificar`. Se falhar, ele desfaz os commits da iteração, os do ticket e os seus.

## Fim da resposta

Termine a resposta com esta linha:

```
<revisao>feita|erro</revisao>
```

- `feita`: revisão concluída, correções commitadas, `make verificar` verde.
- `erro`: problema do ambiente (skill ausente, ferramenta quebrada). O loop para.
