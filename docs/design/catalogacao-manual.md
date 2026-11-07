# Catalogação manual

A catalogação manual existe para o editor acrescentar o que o modelo não viu e corrigir o que ele errou, gastando o mínimo de tempo. Cada mudança continua sendo uma **correção** ([GLOSSARY.md](../../GLOSSARY.md)): uma camada por cima da saída do modelo, com autor, data e motivo, que nunca a apaga.

## O que já existe

O código da E3 já tem a base, para quem tem a permissão `decupagem.editar` (Editor e Curador):
- 14 tipos de correção (`api/correcoes.py`): renomear pessoa, "não é esta pessoa", trocar aparição por menção e o contrário, acrescentar aparição, título e resumo da pauta, tempos (com alças arrastáveis na linha do tempo e passo de 0,1 s ou 1 s pelas setas), descrição e "plano limpo" do plano, texto da fala, marca e tipo do comercial, acrescentar comercial;
- histórico com desfazer;
- fila de revisão para as correções que não casam depois de reprocessar;
- aprovação pelo Curador, por tipo de correção.

Essa parte não foi vista no dev: a conta usada tem os papéis padrão (Consulta e Operador), e os controles não aparecem. A análise vem do código (`web/src/Video.tsx`) e dos testes.

O que pesa hoje:
- **Toda correção abre um formulário** e exige um motivo escrito (`Motivo` tem `min_length=1`). Para trocar "não identificado" por "Leão Lobo" o editor abre um menu, escolhe a ação, digita o nome, digita o motivo e salva.
- **Não há trecho novo.** Dá para acrescentar uma aparição ou um comercial, mas não marcar um trecho no vídeo e dizer o que há nele (uma pessoa, um objeto, um texto na tela, uma pauta).
- **Não há sugestões nem nomes conhecidos.** O nome é texto livre, e a mesma pessoa pode virar "Sabrina Sato" num vídeo e "Sabrina" no outro.
- **Não há objetos**, porque o esquema 1.2 não os tem (ver [busca-e-decupagem.md](busca-e-decupagem.md)).

## Proposta

### 1. Modo de catalogação no próprio visualizador

`E` liga e desliga o modo. A tela continua a mesma, com player e painel lado a lado, e o modo só acrescenta os controles. O editor nunca perde o vídeo nem o tempo em que estava.

```
┌───────────────────────── player ─────────────────────────┐ ┌──── painel ─────────────────┐
│                                                          │ │ Pessoas  Objetos  Pautas …  │
│                                                          │ │ ─────────────────────────── │
│                                                          │ │ ? Sugestões (3)             │
│                                                          │ │   É Leão Lobo?   S  N  R    │
│                                                          │ │   (perfil do TV Fama)       │
│                                                          │ │   Pauta para 44:20–49:19?   │
│                                                          │ │ ─────────────────────────── │
│                                                          │ │ ▸ não identificado  03:31   │
└──────────────────────────────────────────────────────────┘ │   homem de barba, terno     │
 Pautas    ██████░░░████████████                             │ ▸ Felipe Camargo · citado   │ Pessoas   ██ ███   ████  ███                                │ …                           │
 Objetos     ▌▌  ▌      ▌▌▌                                  └─────────────────────────────┘
 Trecho        [I━━━━━━━O]  12:04–12:11   A acrescentar
```

### 2. Sugestões que o editor confirma com uma tecla

> **Saiu** em 6/11/2026 (decisão do Bruno, #487): as sugestões, o painel de sugestões e a contagem por tipo. O que está abaixo sobre elas é histórico.

O sistema já tem pistas que o editor só precisa confirmar. Cada sugestão aparece no topo do painel, com o trecho, e se resolve com `S` (sim), `N` (não) ou `R` (outro nome, com autocompletar). Uma sugestão aceita vira a correção correspondente, com o motivo preenchido ("sugestão confirmada pelo editor"). O motivo continua existindo, como manda o glossário, mas o editor não precisa escrevê-lo.

| Pista | Sugestão | Correção que gera |
| --- | --- | --- |
| GC de identificação (texto na tela do tipo `gc`, com nome e função) enquanto há um "não identificado" na imagem | "É X?" | `pessoa.renomear`, e a menção no texto passa a aparição (`pessoa.mencao_para_aparicao`) |
| "Não identificado" cuja descrição combina com uma pessoa do perfil do programa ("homem de óculos e barba branca" no TV Fama) | "É Leão Lobo?" | `pessoa.renomear` |
| Palpite do modelo sem prova ([ADR 0005](../adr/0005-identificacao-por-referencia.md)) | "O modelo acha que é X. Confirma?" | `pessoa.renomear`; a confirmação do editor é a prova |
| Pessoa renomeada num vídeo | "Aplicar às outras 6 aparições desta pessoa neste vídeo?" | Uma correção só, porque a pessoa é uma entidade |
| Trecho do vídeo sem pauta | "Criar uma pauta de 44:20 a 49:19?" | Pauta nova (tipo a criar) |
| Visual da aparição cita uma peça que não está nos objetos ("vestido vermelho") | "Acrescentar vestido vermelho da Sabrina?" | `objeto.acrescentar` (tipo a criar) |

Regra da [ADR 0005](../adr/0005-identificacao-por-referencia.md): o perfil e o catálogo tornam a pessoa candidata, mas não confirmam o nome. A sugestão nunca muda nada sozinha; é o editor quem confirma.

Só o GC de identificação sustenta uma sugestão; a **chamada** nunca. No clipe4, às 03:55, a chamada "Ex-marido Felipe Camargo conta sua versão" está na tela enquanto o apresentador fala; o Felipe Camargo não aparece. Uma regra que lesse qualquer texto na tela sugeriria o nome errado, o mesmo erro que levou à ADR 0005. A decupagem 1.2 já separa `gc` de `chamada` em `textos_na_tela`, e esse campo decide.

### 3. Nomes, marcas e objetos já conhecidos enquanto digita

Todo campo de nome é um autocompletar sobre o catálogo:
- **Pessoas**: nome, apelidos e grafias aproximadas, sem diferença de acento e maiúscula. "sabrin" oferece "Sabrina Sato (apresentadora)". Escolher do catálogo liga a correção ao id da pessoa, e não a um texto. Um nome novo pede `Shift+Enter` e entra no catálogo como novo, para o Curador revisar.
- **Marcas**: o catálogo de marcas do Curador.
- **Objetos**: o tipo ("sandália", "vestido") oferece os tipos já vistos no acervo; a cor base é a lista fechada do esquema, escolhida por tecla.

### 4. Marcar um trecho e dizer o que há nele

1. `I` marca a entrada no tempo atual e `O` marca a saída. O trecho aparece na linha do tempo e pode ser ajustado pelas alças que já existem.
2. `A` abre um campo único com o tipo em abas: `1` Pessoa, `2` Objeto, `3` Marca, `4` Texto na tela, `5` Pauta. Cada aba mostra os campos daquele tipo, com autocompletar.
3. `Enter` salva. O trecho some, a correção entra no histórico e o item aparece na faixa certa.

Um trecho de pessoa já sai como aparição (na imagem). Para menção, um campo "Citada" troca a lista, como no formulário atual.

### 5. Tudo pelo teclado

| Tecla | Ação |
| --- | --- |
| `E` | Liga e desliga o modo de catalogação |
| `↑` `↓` | Item anterior e seguinte no painel; o player acompanha |
| `Enter` | Salta o player ao item |
| `S` `N` `R` | Sugestão: sim, não, outro nome |
| `I` `O` | Entrada e saída do trecho |
| `A` | Acrescentar o que há no trecho |
| `F2` | Corrigir o item em foco (nome, atributos, tempos) |
| `Del` | "Não é isto" no item em foco, com confirmação na mesma linha |
| `M` | Marca ou desmarca a pauta em foco para juntar |
| `U` | Junta as pautas marcadas (seguidas), com o título de uma delas ou um novo |
| `D` | Divide a pauta em foco no ponto do player, com os dois títulos |
| `Ctrl+Z` | Desfaz a última correção do editor (a rota de desfazer já existe) |
| `Esc` | Fecha o campo aberto sem salvar |

Os atalhos do player (Espaço, J/K/L, ←/→) valem também no modo de catalogação, menos quando o foco está num campo de texto.

### 6. Estado visível

Cada correção mostra onde está: **salva**, **indexando** e **na busca**, como pede o plano. O estado sai do estado da indexação do Job (`na_busca` no histórico, `GET /v1/jobs/{id}/correcoes`): não há registro por correção. A tela pergunta de novo a cada 2 s enquanto houver "indexando". Uma correção que exige aprovação mostra "aguardando o Curador" e fica fora da decupagem entregue até ser aprovada.

## O que medir

- **Tempo de catalogação por hora de vídeo**, que é a métrica de utilidade do plano. A meta do redesenho é baixar esse número.
- **Sugestões aceitas e recusadas por tipo.** Uma sugestão muito recusada deve sair.
- **Correções por tipo e por programa**, que mostram onde a decupagem erra e vão para o painel.

## Novos tipos de correção

| Tipo | Para quê |
| --- | --- |
| `objeto.acrescentar` | Objeto que o modelo não viu, com categoria, tipo, cor, dono e trecho |
| `objeto.atributos` | Corrigir tipo, cor ou marca |
| `objeto.dono` | Trocar ou tirar a pessoa ligada ao objeto |
| `objeto.nao_existe` | Objeto que não está na imagem |
| `texto_na_tela.acrescentar` | GC que o modelo não leu |
| `pauta.acrescentar` | Pauta num trecho sem pauta |

Os campos novos do esquema 1.2 (texto na tela, tom, fontes do nome, papel e visual) já estão em #75, no PR #89.
