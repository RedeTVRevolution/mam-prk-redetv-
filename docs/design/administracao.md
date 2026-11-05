# Administração

A administração é a área do papel Administrador, que só existe em conta local com MFA (plano, "Usuários, login e permissões"). Ela serve para manter o sistema e, quando preciso, apagar com segurança. Não é um console de nuvem: o que o Terraform e o GCP já fazem (armazenamento, ciclo de vida, rede) fica fora da tela.

## O que o administrador faz

| Tarefa | Hoje | Proposta |
| --- | --- | --- |
| Criar conta local e reenviar o link de senha | `make criar-contas` | Tela de usuários: e-mail, nome, papéis. Reenviar o link é um botão |
| Dar e tirar papéis, limitados a programas | `make atribuir-papeis` (sem escopo por programa) | Na mesma tela, papéis e programas por usuário |
| Desativar um usuário | Não existe | Desativar bloqueia o login no Identity Platform e encerra as sessões. Nunca se apaga a conta: as correções guardam o autor |
| Emitir, listar e revogar chaves de API | `make emitir-chave`, `listar-chaves`, `revogar-chave` | Tela de sistemas: a chave aparece uma vez na criação; revogar vale na hora |
| Definir quais correções exigem aprovação | Aba "Regras de aprovação" (`/v1/admin/aprovacao`, permissão `aprovacao.definir`, só do Administrador; antes, `make definir-aprovacao`) | Uma lista de tipos de correção com uma chave liga/desliga. Vale na hora para as correções novas; as pendentes continuam pendentes. Cada mudança vai para a auditoria (`aprovacao.alterada`: tipo, antes, depois) |
| Ver o que aconteceu | Cloud Audit Logs, fora da aplicação | Tela de auditoria: quem, quando, o quê e o motivo, filtrável por pessoa, vídeo e tipo |
| Apagar vídeo, pessoa do catálogo ou marca | Não existe (`DELETE /v1/jobs/{id}` só cancela) | Lixeira, descrita abaixo |

O que **não** é do administrador: reprocessar o que falhou é do Editor e do Curador; aprovar correções, fundir pessoas e manter o catálogo são do Curador; criar, editar e apagar programas, com as pessoas e o papel de cada uma neles (aba **Programas**, permissão `programas.editar`), são do Editor, do Curador e do Administrador; os indicadores são da Diretoria. Os papéis Administrador e Diretoria já existem em `api/papeis.py`.

## Apagar com segurança

### Regras

1. **Apagar é em dois tempos.** Primeiro o item vai para a **lixeira**: sai na hora da busca, do acervo e dos relatórios, mas nada é destruído. Depois de **30 dias** na lixeira, ou antes por decisão do administrador, vem a **purga**, que apaga de fato.
2. **Antes de confirmar, a tela diz o que vai junto**, com números: "1 vídeo, 1 decupagem, 37 correções, 1.240 momentos no índice. O arquivo original no storage da RedeTV não é tocado."
3. **Motivo obrigatório** em todo apagamento, como nas correções.
4. **Confirmação proporcional ao estrago.** Mandar para a lixeira pede um clique de confirmação na própria linha. A purga pede que o administrador digite o nome do item, e exige um login com MFA feito há poucos minutos.
5. **Restaurar** volta tudo como estava, inclusive o índice, enquanto o item estiver na lixeira. A tela mostra os dias que faltam ("purga em 12 dias").
6. **Quem pode** (permissão `catalogo.apagar` para o catálogo; `lixeira.gerir` para restaurar e purgar). Mandar um vídeo para a lixeira é do Administrador; uma pessoa ou marca do catálogo, também do Curador, que cuida do catálogo. Restaurar e purgar são só do Administrador.
7. **O histórico de apagamentos nunca é apagado.** Cada envio para a lixeira, restauração e purga gera um registro com quem, quando, o quê, o motivo e os números do impacto. O administrador lê, mas não edita nem apaga.

### O que acontece com cada coisa ligada ao vídeo

| Ligado ao vídeo | Na lixeira | Na purga |
| --- | --- | --- |
| Original MP4 | Não é nosso: fica no storage da RedeTV | Idem |
| Cópia limpa, proxy de reprodução e quadros-chave (Cloud Storage) | Guardados | Apagados |
| Proxies de escalonamento e de análise | Já somem pela regra de ciclo de vida de 30 dias | — |
| Decupagem do modelo e das janelas | Guardadas | Apagadas |
| Correções | Guardadas | Apagadas, com o registro da purga no histórico |
| Momentos no índice da busca | Saem da busca na hora, por um filtro do servidor ("não está na lixeira"); a restauração é instantânea | Apagados do índice |
| Eventos no BigQuery (painel) | Guardados | Guardados: os números do passado não mudam. O painel mostra "vídeo apagado" no lugar do nome |
| Job | Marcado como apagado, invisível para quem não é administrador | Removido |

### Três cuidados que o código atual impõe

- **Correções só se acrescentam.** O repositório de correções "só acrescenta, nunca altera nem apaga" (`api/correcoes.py:495`), e o glossário diz que a saída do modelo nunca é apagada. Essas regras valem para o trabalho do dia a dia, e a lixeira as respeita: ela não apaga nada. A purga é a única exceção, feita só por um processo da própria purga, que deixa o registro dela no histórico. **Decisão a registrar numa ADR.**
- **Dois jobs podem dividir um processamento.** A chave de conteúdo faz dois jobs com o mesmo arquivo usarem o mesmo processamento (`videos/{chave}`, plano, "Resiliência e duplicidade"). Apagar um job apaga o job e o acesso de quem o enviou. O processamento, os arquivos e o índice só são purgados quando nenhum job aponta mais para eles. A tela avisa: "Este arquivo também foi enviado pelo sistema X; a decupagem continua para ele."
- **Pessoa do catálogo tem dado biométrico.** Apagar uma pessoa do catálogo apaga também as fotos de rosto que ela tenha (ADR 0005, hoje [0012](../adr/0012-sem-referencias-de-rosto-na-web.md): a busca na web saiu e a migração apagou as antigas). Rosto é dado sensível pela LGPD, então essas fotos não esperam os 30 dias: saem já no envio para a lixeira. Nas decupagens, as aparições confirmadas pelo rosto voltam a "não identificado"; as confirmadas por GC ou fala mantêm o nome. Antes de apagar, a tela oferece **fundir** com outra pessoa, que é o caso mais comum (nome duplicado); a permissão é `catalogo.fundir` (Curador e Administrador). Renomear a pessoa em todos os vídeos pede `correcao.aprovar` (Curador).

### Outros apagamentos

| Item | Como se apaga |
| --- | --- |
| Usuário | Não se apaga: desativa. Um pedido de exclusão pela LGPD anonimiza o nome e o e-mail no histórico e mantém o uid. Decisão a confirmar com o jurídico |
| Chave de API | Não se apaga: revoga. A chave revogada fica na lista, marcada |
| Marca do catálogo | Lixeira; as ocorrências nas decupagens mantêm o texto da marca e perdem o vínculo |
| Correção | Não se apaga: desfaz-se, pela rota que já existe |

## Telas

```
Administração
  Usuários   Sistemas e chaves   Aprovação   Lixeira   Auditoria

Lixeira                                                      Filtro: Tudo ▾
  Item                         Tipo     Apagado por   Em          Purga em   Motivo
  TV Fama 21/10/2026           Vídeo    Ana Lima      28/10 14:02  26 dias   duplicado
  "Sabrina S."                 Pessoa   Rui Prado     27/10 09:40  25 dias   fundida
                                                      [Restaurar]  [Purgar agora…]
```

Tabelas densas, sem cartões: o administrador procura uma linha, não navega por uma vitrine.
