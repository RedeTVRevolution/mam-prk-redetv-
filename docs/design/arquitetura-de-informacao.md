# Arquitetura de informação

As telas do MAM, o caminho entre elas e, para cada uma, o que já existe no código, o que existe sem tela e o que falta. A referência é o código da `main` em 30/10/2026 (`web/src/`, `api/`) e a navegação no dev com uma conta de papéis padrão (Consulta + Operador). Os prints estão em [`prints/app/`](prints/app/).

## Mapa

```
Barra fixa:  MAM · [ Buscar no acervo…  / ] · Acervo · Pessoas · Painel · Administração · conta
                                                       (Curador) (Diretoria) (Administrador)

Busca ──clique no momento──▶ Visualizador (vídeo, t=12:04, momentos da busca marcados)
Acervo ──clique no vídeo───▶ Visualizador
Visualizador ──E──▶ modo de catalogação (mesma tela, para Editor e Curador)
Visualizador ──clique numa pessoa──▶ Pessoas › ficha da pessoa ──▶ Busca por ela
```

Princípios do mapa:
- **A busca está em toda tela**, na barra, e `/` a foca de qualquer lugar. É a porta principal; o acervo é a porta secundária.
- **Toda tela tem endereço.** `/busca?q=sapato+vermelho`, `/video/{id}?t=724`, `/pessoas/{id}`. Hoje o vídeo abre sem mudar a URL ([print](prints/app/03-video-aberto.jpg)): não dá para mandar a um colega o link de um momento, nem voltar a ele pelo histórico do navegador.
- **Catalogar não é outra tela.** É um modo do visualizador. O editor que acha um erro corrige ali mesmo, sem perder o vídeo e o tempo.
- **O menu mostra só o que o papel pode usar**, como o plano já define. A API confere tudo de novo.

## Mockup, nossa aplicação e benchmark, lado a lado

| Padrão | Mockup do Ilton | Nossa aplicação hoje | Benchmark | Decisão |
| --- | --- | --- | --- | --- |
| Painel acompanha o vídeo | Sim, troca a pauta sozinho | Destaca a fala atual | Azure VI sincroniza a transcrição | Manter, com destaque neutro |
| Faixas por tipo na linha do tempo | Só pautas | Sete faixas | Azure VI, por tipo de insight | Manter as sete e somar Objetos |
| Trechos sem decupagem à mostra | Sim, hachurados | Não | Não visto | Adotar |
| Aparição separada de menção | Não | Sim | Não visto | Manter: é o que torna a busca por pessoa confiável |
| Prova do nome | Não | Fontes do nome (GC, fala) | Azure VI dá uma confiança em % | Manter a fonte; não usar % |
| "Reproduzir trecho" até o fim | Sim | Não | Não visto | Adotar |
| Busca | Filtra as pautas de um vídeo e pinta a linha do tempo | Não existe | Acervo inteiro, agrupado por vídeo (Twelve Labs), marcas na barra (Frame.io) | Construir na E2, com o "por que casou" |
| Atalhos | Espaço/K, ←/→ 5 s, J/L 10 s | Só os do player nativo | J/K/L e quadro a quadro (Frame.io), ↑/↓ entre ocorrências (CatDV) | Tabela de [principios.md](principios.md) |
| Miniaturas | Geradas no navegador, a pedido | Um `<video>` por miniatura | Quadro-chave do servidor | Quadros-chave na validação |
| Objetos | Cenários sem tempo; figurino em texto | Lista livre por plano; visual em texto | Azure VI, objetos com tempo | Esquema 1.3 |
| Catalogação | Nenhuma | Formulários com motivo, para Editor e Curador | I/O e tags (iconik), marcador por tecla (CatDV) | Modo de catalogação pelo teclado |
| Endereço da tela | Uma página só | O vídeo abre sem mudar a URL | Link para o ativo e o tempo | Rotas com tempo |

## Telas

### Busca (E2)

| | |
| --- | --- |
| Para quem | Todos os papéis com `decupagem.ver` |
| O que tem | Caixa de busca, chips de tipo de evidência, filtros de programa e ano, resultado agrupado por vídeo com os momentos. Detalhes em [busca-e-decupagem.md](busca-e-decupagem.md) |
| Existe no código | Nada |
| Existe sem tela | Nada. A rota `/v1/busca` não existe |
| Falta | Tudo: índice de momentos, entendimento da consulta, rota, tela. E, antes, os dados que a busca exige: objetos com atributos, quadros-chave, data de exibição, catálogo de pessoas |

### Acervo (hoje "Biblioteca")

| | |
| --- | --- |
| Para quem | Todos; o envio só para quem tem `video.enviar` |
| O que tem hoje | Grade de cartões com nome do arquivo, estado, data do envio, duração e o código da falha; filtro por estado; seletor de programa e botão "Enviar MP4" na coluna da esquerda ([print](prints/app/02-biblioteca.jpg)) |
| Problemas vistos | Cartões sem miniatura, só um ícone. O selo "Falhou" cortado em "FAL…". O código interno (`codec_nao_suportado`) mostrado como mensagem. O seletor "Programa" é do envio, mas fica onde se espera um filtro. Dois "clipe2.mp4" iguais, sem nada que os distinga. Sem busca por nome e sem ordenação |
| Proposta | Tabela densa em vez de cartões: miniatura pequena, nome, programa, **data de exibição**, duração, estado e quem enviou. Filtros por programa, ano e estado. Envio num botão que abre um diálogo com o arquivo, o programa e a data. A falha em português ("O vídeo usa um codec que não aceitamos: envie em H.264"), com o código à parte para o suporte |
| Existe no código | `GET /v1/jobs`, `POST /v1/jobs` com programa, upload retomável, consulta periódica do estado |
| Falta | Data de exibição no Job, miniatura do vídeo, busca por nome, paginação para um acervo de milhares de vídeos (a lista vem inteira) |

### Visualizador (hoje "Vídeo")

| | |
| --- | --- |
| Para quem | Todos com `decupagem.ver` |
| O que tem hoje | Player nativo do navegador; tempo atual; linha do tempo com sete faixas (pautas, aparições, menções, comerciais, planos, fala e texto na tela); painel com seis abas (Pessoas, Pautas, Marcas, Planos, Fala e Texto na tela); botão para baixar o JSON ([prints](prints/app/)) |
| O que funciona | Clicar num item salta o player ao tempo certo. A fala atual fica destacada enquanto o vídeo toca. Aparição e menção ficam separadas ("Só citadas (não contam como tempo de tela)"). Pessoa sem prova fica "não identificado", com a descrição |
| Problemas vistos | O destaque da fala atual é um bloco vermelho cheio, a cor da marca usada como alerta ([print](prints/app/10-fala-tocando.jpg)). A aba Marcas vazia não diz que está vazia ([print](prints/app/06-aba-marcas.jpg)). As miniaturas são players de vídeo (`<video #t=>`), uma por aparição. Nenhum atalho de teclado fora do player: Espaço, L e → não fizeram nada com o foco na página. Os marcadores da linha do tempo têm nome acessível só com o tipo e o tempo ("Aparições 00:55"), sem dizer quem ou o quê. Não há endereço próprio |
| Proposta | Player e painel fixos lado a lado; só o painel rola. Uma faixa a mais, **Objetos**, e as faixas com contagem. Atalhos da tabela em [principios.md](principios.md). A busca dentro do vídeo filtra o painel e marca a linha do tempo. Lacunas da decupagem (trechos sem pauta) hachuradas, como no mockup |
| Existe no código | `GET /v1/jobs/{id}/decupagem` e `/reproducao`; `Video.tsx` com faixas, abas e saltos |
| Falta | Quadros-chave, faixa e aba de objetos, atalhos globais, endereço por vídeo e por tempo, navegação entre os momentos de uma busca |

### Catalogação manual

| | |
| --- | --- |
| Para quem | Editor (corrige) e Curador (corrige e aprova) |
| O que tem hoje | No código, para quem tem `decupagem.editar`: menu por ocorrência, formulários para corrigir pessoa, aparição ou menção, tempos (com alças arrastáveis na linha do tempo), pauta, plano, fala e comercial, todos com campo "Motivo"; histórico com desfazer; fila de revisão das correções que não casaram depois de reprocessar; aprovar e recusar para o Curador. **Não foi visto no dev**: a conta usada tem os papéis padrão, sem `decupagem.editar`, e os controles não aparecem |
| Proposta | Modo de catalogação no próprio visualizador, todo pelo teclado, com sugestões para confirmar. Detalhes em [catalogacao-manual.md](catalogacao-manual.md) |
| Existe no código | `POST /v1/jobs/{id}/correcoes` com 14 tipos, desfazer, fila, reaplicar, descartar, aprovar e recusar (`api/jobs.py`, `api/correcoes.py`) |
| Existe na Administração | A regra de quais tipos exigem aprovação: aba "Regras de aprovação" |
| Falta | Correção de objetos (o esquema não tem), de texto na tela, tom e fontes do nome (#75, no PR #89), marcar um trecho novo por entrada e saída, autocompletar de pessoas e marcas, sugestões para confirmar |

### Pessoas (catálogo)

| | |
| --- | --- |
| Para quem | Todos leem; o Curador edita |
| O que tem | Lista de pessoas do catálogo com nome, apelidos, papel, as 3 referências de rosto com a página de origem, e os vídeos em que aparece. Na ficha: renomear, fundir duas pessoas, trocar uma referência de rosto, ver as menções e as aparições |
| Existe no código | Só o perfil do programa, em `api/programas.toml` (4 pessoas do TV Fama) |
| Falta | Catálogo no banco, referências de rosto (ADR 0005, #82), id estável entre vídeos, tela |

### Painel da diretoria (E9)

| | |
| --- | --- |
| Para quem | Diretoria e Administrador |
| O que tem | Os indicadores do plano (acessos, vídeos, buscas, revisão, API e custo), com filtros por período, programa e usuário |
| Existe no código | Papel Diretoria (`painel.ver`), o registro de cada abertura e exportação na auditoria, os eventos de uso e as tabelas resumidas no BigQuery, as rotas `/v1/painel/...` com filtros e CSV (`api/painel.py`) e a tela `/painel/<aba>` com as abas Acessos, Vídeos e Buscas |
| Falta | As abas de revisão e API (#284) e custo (#285). Uma coisa a mais para o redesenho: **taxa de correção por tipo** (onde a decupagem erra) |

### Administração

| | |
| --- | --- |
| Para quem | Administrador, só em conta local com MFA |
| O que tem | Usuários, papéis, chaves de API, regras de aprovação, lixeira e auditoria. Detalhes em [administracao.md](administracao.md) |
| Existe no código | `GET /v1/eu` com papéis e permissões; `DELETE /v1/jobs/{id}`, que só cancela |
| Existe sem tela | Criar contas (`make criar-contas`), dar papéis (`make atribuir-papeis`), chaves de API (`make emitir-chave`, `listar-chaves`, `revogar-chave`) |
| Falta | Tela de usuários, apagar vídeo (lixeira), auditoria visível |

## Resumo: o que existe, o que existe sem tela, o que falta

| Área | Existe com tela | Existe sem tela | Falta |
| --- | --- | --- | --- |
| Login | Conta local com TOTP | Contas criadas por script | Login RedeTV (E8) |
| Acervo | Lista, filtro por estado, envio com programa | — | Data de exibição, miniatura, busca por nome, paginação |
| Visualizador | Player, sete faixas, seis abas, salto, destaque da fala | — | Objetos, quadros-chave, atalhos, endereço por tempo |
| Busca | — | — | Tudo (E2) |
| Catalogação | Correções, histórico, fila e aprovação (para Editor e Curador) | Regra de aprovação | Objetos, trecho novo, autocompletar, sugestões |
| Pessoas | — | Perfil do programa no TOML | Catálogo, referências de rosto, tela |
| Painel | — | Papel Diretoria e auditoria do acesso | Indicadores, tela (E9) |
| Administração | — | Contas, papéis, chaves, aprovação por script | Telas, lixeira, auditoria |
