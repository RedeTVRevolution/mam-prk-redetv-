# Sistema visual

> Saiu em 06/11/2026 (decisão do Bruno, #487): as sugestões, o painel de sugestões e a contagem por tipo. O que está abaixo sobre elas é histórico.

O porquê das decisões visuais da interface do MAM e as regras que os testes guardam. Cada decisão aplica um item dos [princípios](principios.md), citado entre parênteses (P1 a P9).

As tabelas de cor, tipo, medida, ícone e componente moram no [MAM_DESIGN_SYSTEM.md](MAM_DESIGN_SYSTEM.md), que é a referência. Este arquivo não as repete: explica o que o outro não explica e diz onde a interface construída se afasta dele.

A interface é a de `web/src/novo/` (Tailwind v4 e shadcn/ui; [ADR 0014](../adr/0014-frontend-novo-tailwind-shadcn.md)). Onde está cada valor:

| O quê | Fonte |
| --- | --- |
| Cores de superfície, texto, foco e estado; fontes; tamanhos; raios; sombra; cores de gráfico | [`web/src/novo/index.css`](../../web/src/novo/index.css) |
| Cor de cada tipo de ocorrência, de cada estado do Job (`ESTADOS_DO_JOB`) e de cada cor base de objeto | [`web/src/cores.ts`](../../web/src/cores.ts) |

Os testes que guardam as regras:

- [`novo/tokens.test.ts`](../../web/src/novo/tokens.test.ts): contraste WCAG de cada par texto/fundo, selos de estado, foco sobre o painel, distinção das sete cores de tipo na deuteranopia, o âmbar de "Decupando", primário diferente do vermelho da marca, raios até 6 px, uma sombra só, cores e escala dos gráficos.
- [`estilo.test.ts`](../../web/src/estilo.test.ts): em todo arquivo de `web/src`, nenhum gradiente (nem `bg-linear-`), nenhum `backdrop-blur`, nenhuma sombra do Tailwind nem acima de 8 px de desfoque, nenhum emoji ou símbolo tipográfico.
- [`cores.test.ts`](../../web/src/cores.test.ts): toda cor base do objeto tem a sua cor.

## Cores

A interface é cinza, e a cor só aparece quando diz alguma coisa (P3). Só tema escuro (P9). Superfícies, texto e contraste: [MAM_DESIGN_SYSTEM, seção 2.1](MAM_DESIGN_SYSTEM.md). Todo texto, inclusive o secundário, passa no AA (4,5:1) sobre `canvas`, `painel`, `elevado` e `sobreposto` (P8). O texto desabilitado (`subtle`) é isento (WCAG 1.4.3), por isso é só para controle desabilitado. O placeholder usa o texto secundário, porque o campo está ativo.

### Foco e seleção

Um azul só, `#3871DC`, para o anel do teclado, o botão primário, a barra de 3 px do item atual e o item ativo do trilho (P3). O texto na cor de foco (link, valor de filtro ativo) usa a versão clara, `#82AAF5`. A linha ou o cartão selecionado usa o foco a 16% sobre o painel, já misturado (`#1A2538`). Tabela completa: [seção 2.2](MAM_DESIGN_SYSTEM.md).

- **Por que este azul.** Ele cumpre dois papéis ao mesmo tempo. O branco sobre ele passa no AA (4,6:1), então serve de fundo do botão primário. E ele próprio passa de 3:1 sobre `painel`, `elevado` e `sobreposto` (3,9, 3,6 e 3,3), o mínimo da WCAG para um indicador gráfico (1.4.11), então serve de anel e de barra. Mais claro, o texto branco do botão reprova; mais escuro, o anel some sobre a superfície elevada.
- **O anel nunca encosta em `controle`**, onde o azul dá só 2,9:1. O anel é o contorno global de 2 px com 2 px de afastamento, então fica sobre o painel.
- **O primário é o foco, não um neutro.** `--color-primary` e `--color-ring` têm o mesmo valor, e o teste confere. Um primário cinza deixaria o botão principal de um diálogo igual ao "Cancelar".

### Estados

| Estado | Cor | Estados do Job |
| --- | --- | --- |
| Concluído | `ok` (`#5CC98A`) | Concluído |
| Em andamento ou aguardando | `andamento` (`#E5B045`) | Aguardando envio, Em quarentena, Decupando, Finalizando |
| Falhou | `destructive` (`#F4736A`) | Falhou |
| Inerte | `muted-foreground` | Cancelado |

- **Verde, âmbar, vermelho** (P3): a convenção que o operador já conhece. "Decupando" deixou o azul, que é a cor de foco: um estado nunca pode parecer seleção.
- **"Aguardando envio" e "Em quarentena" também são âmbar**, porque o vídeo ainda não está pronto e ninguém precisa agir. A palavra no selo os distingue.
- **"Finalizando" não é um estado da API.** É o Job concluído cujas etapas depois da análise ainda rodam. Aparece em âmbar, como em andamento.
- **"Cancelado" é cinza**: não terminou nem falhou, e não pede atenção.
- **Selo:** a cor do estado no texto, sobre a mesma cor a 12%. O teste confere o AA nesse par. Um valor só por estado serve aos dois usos.
- **Nunca só cor** (P3): o selo leva sempre a palavra e o ícone. Detalhes do selo e do *tally* da miniatura: [seção 2.3](MAM_DESIGN_SYSTEM.md).

### Tipos de ocorrência

Uma cor fixa por tipo, a mesma na faixa da linha do tempo, no chip de filtro e no marcador do inspetor (P3). Os valores estão na [seção 2.5](MAM_DESIGN_SYSTEM.md) e em `CORES_DE_OCORRENCIA`.

- **Legíveis como texto.** As sete passam no AA sobre `canvas`, `painel`, `elevado` e `sobreposto`. O chip ligado escreve o nome do tipo na cor dele, e nenhuma cor precisa de regra à parte. Sobre `controle`, a fala cai para 4,3:1, por isso texto de tipo nunca vai sobre `controle`.
- **Fora do vermelho e do azul de foco.** Nenhum tipo usa o vermelho (que é marca e falha) nem o azul do foco: um bloco de pauta selecionado não pode sumir na cor da seleção. A pauta é um lilás-azulado, mais claro e mais violeta que o foco.
- **A fala é cinza.** É a faixa mais densa e contínua; em cinza, ela forma o fundo de referência e deixa as outras saltarem.
- **O plano não é faixa.** Só tem seção no inspetor, em `muted-foreground`.
- **Hachurado** (P5): o trecho sem decupagem é riscado em diagonal, listras de 2 px a cada 6 px, na cor `border-strong`. É o único `repeating-linear-gradient` permitido: desenha um padrão, não uma transição de cor (o `estilo.test.ts` só aceita esse).
- **Momentos da busca** na linha do tempo usam o azul do texto de foco (`link`).

**Como a distinção foi conferida.** O teste `as sete cores se distinguem na visão comum e na deuteranopia`:

1. converte cada cor para RGB linear;
2. simula a deuteranopia completa com a matriz de Machado, Oliveira e Fernandes (2009);
3. mede a distância euclidiana entre todo par no Oklab (Ottosson, 2020), um espaço em que distância acompanha a diferença percebida;
4. exige pelo menos 0,10 entre qualquer par, na visão comum e na simulada.

O limiar de percepção no Oklab fica perto de 0,02; 0,10 é uma diferença que se vê de relance num bloco pequeno. Resultado: o par mais próximo na visão comum é pauta/fala, com 0,137; na deuteranopia, menção/fala, com 0,104. Na protanopia, que nenhum teste cobre, o par mais próximo é menção/fala, com 0,046: distinguíveis lado a lado, mas não de relance. Como a cor nunca é a única pista (cada faixa tem ícone e nome, e cada bloco, nome acessível), isso fica registrado como limite conhecido.

Sete tons distinguíveis na deuteranopia, todos com AA sobre fundo escuro, sem vermelho e sem o azul do foco: o espaço é apertado, e as cores saíram de uma busca numérica sob essas restrições, ajustada à mão depois. Quem trocar uma cor precisa rodar o teste.

### Cor do objeto

`CORES_DE_OBJETO`, em `cores.ts`, dá uma cor a cada valor de `cor_base` do Objeto (esquema 1.3): `vermelho`, `laranja`, `amarelo`, `verde`, `azul`, `roxo`, `rosa`, `marrom`, `bege`, `preto`, `branco`, `cinza`, `dourado`, `prateado` e `estampado`. É a única exceção à regra de nomear a cor pela função e não pelo tom, porque aqui o tom é o dado: a chave é o valor do esquema, e a cor representa a peça que aparece no vídeo, não a interface. Por isso, ela é diferente da cor do tipo de ocorrência `Objeto`.

- **Só no quadradinho de 10 px** da lista de objetos do inspetor, no máximo dois por objeto, com borda de 1 px em `muted-foreground`, que separa o `preto` do fundo. Nunca vira texto, fundo nem faixa.
- **Sempre com a palavra** (P3): o tom em palavras ("dourado e preto") ao lado. O quadradinho é `aria-hidden`, e o teste do inspetor confere isso e a palavra.
- **`estampado` não tem uma cor só**: usa o cinza do texto secundário, e a palavra diz o resto.

### Marca RedeTV

`marca` (`#E03131`) é só do logotipo. Na TV, vermelho quer dizer "no ar" ou erro (P3). Ele não aparece em botão, destaque, faixa nem fundo. Hoje o logotipo é a imagem `web/src/assets/redetv-logo.png`, e nenhuma classe usa o token. O vermelho de erro é outro, `destructive`, e vale para tudo o que diz "deu ou vai dar errado": o selo "Falhou", o alerta de erro, o campo inválido e o botão de perigo.

O botão de perigo é **contornado**, nunca cheio: o branco sobre `#F4736A` dá menos de 3:1, abaixo do AA. O `button.tsx` já traz a variante certa (`destructive`).

## Tipografia

IBM Plex Sans (400, 500 e 600) para a interface e IBM Plex Mono (400) para timecode e duração, onde cada caractere conta. As duas vêm do `@fontsource`, só o subconjunto latino, empacotadas no build: nenhum pedido a outro servidor. Escala e regras: [seção 3](MAM_DESIGN_SYSTEM.md).

- **Padrão de 13 px** no `body` (`text-sm`), inclusive na transcrição e na lista de falas do inspetor. O 14 (`text-base`) aparece no texto de diálogo e na ficha do item do inspetor (P1). Título de página 20 px (`text-xl`) e de diálogo 16 (`text-lg`), em 600; título de painel é 13 px e o do inspetor, 12. Título nomeia a seção, não faz manchete.
- **Algarismos tabulares em todo o `body`**: `11:11` e `48:08` ocupam a mesma largura, e as colunas se alinham (P5).
- **600 no máximo.** O 700 "acende" demais no escuro.
- **Frase normal sempre**, sem caixa alta em rótulo, aba ou cabeçalho.

## Forma e movimento

- **Bordas de 1 px**, em `border`; contorno de campo e chip em `border-strong`. Painéis encaixados se separam por uma costura de 1 px, sem sombra (P2).
- **Cantos por hierarquia, nenhum acima de 6 px** (P2): 0 no painel encaixado, 2 px (`xs`) em bloco da linha do tempo, selo e barra; 4 px (`sm`) em botão, campo, chip e cartão; 6 px (`md`) no que flutua. Os nomes `lg` e acima do shadcn também valem 6 px. O círculo (`rounded-full`) aparece em peça pequena: avatar, marcador, polegar do slider, interruptor.
- **Uma sombra só**, `shadow-float` (`0 4px 8px`), para menu, popover, dica e diálogo. As sombras do Tailwind foram desligadas no tema. Nada de gradiente, brilho ou vidro fosco (P2). O fundo do diálogo é `bg-black/60`, chapado.
- **Animação só para orientar** (P9): 150 ms ao abrir menu, popover, diálogo e trilho. Com `prefers-reduced-motion`, tudo vira troca imediata. Só giram o ícone de "Decupando" e o de carregando.
- **Ícones**: só os do Tabler, com `stroke` 1,75 como regra; o estado vazio usa 1,5 e os selos usam 2. Sempre com rótulo à vista ou dica (P2). Nada de emoji nem símbolo tipográfico; o teste procura pictogramas, formas geométricas (`▦ ◫ ●`), símbolos diversos e dingbats.

## Componentes

Os componentes são os do shadcn/ui, em `web/src/novo/ui/`, ajustados ao tema. O catálogo está na [seção 12](MAM_DESIGN_SYSTEM.md); aqui ficam as regras de uso que o código segue.

| Componente | Regra | Onde no código |
| --- | --- | --- |
| Botão primário | Fundo `primary`, texto branco; a ação principal do diálogo ou formulário, no máximo uma por bloco. Nunca vermelho | `ui/button.tsx`, variante `default` |
| Botão secundário e de ícone | `secondary` (Cancelar, ações secundárias) e `ghost` (ícone, cinza). Todo botão de ícone tem dica e `aria-label` | `ui/button.tsx`, `size-7` |
| Botão de perigo | Contornado em `destructive`, sempre com confirmação | `ui/button.tsx`, variante `destructive` |
| Campo | Fundo `input`, borda `border-strong`, rótulo acima | `admin/comum.tsx` (`CAMPO`), nativo (`<select>`, `<input type="date">`) |
| Busca | A barra de 40 px mostra "Buscar no acervo…" e a tecla `/`; `/` ou `Ctrl K` abre a paleta de comandos, não foca o campo (P6) | `Casca.tsx` |
| Chip de faixa | Desligado: contorno `border-strong`, texto cinza. Ligado: contorno e nome na cor do tipo. Sempre ícone e contagem; `aria-pressed` | `video/LinhaDoTempo.tsx` (`ChipsDasFaixas`) |
| Selo de estado | Cor do estado a 12%, ícone e palavra, sem caixa alta | `comum/SeloDeEstado.tsx` |
| Selo "não confirmado" | Contorno `border-strong`, texto cinza, com dica: pessoa ou sugestão que ninguém confirmou (P5) | `video/Inspetor.tsx` |
| Tabela | Cabeçalho e linha de 32 px; hover um degrau mais claro; linha aberta em `selected`. Só na Administração e nos relatórios. Não ordena por coluna | `admin/comum.tsx` (`TABELA`) |
| Item atual do inspetor | Barra de 3 px em `primary` à esquerda e fundo `card`, nunca um bloco colorido; `aria-current`. **Selecionado**: `selected` | `video/Inspetor.tsx` (`ATUAL`) |
| Seção do inspetor | Cabeçalho de 36 px com o ícone na cor do tipo, o nome e a contagem (zero aparece como zero); abre e fecha com `aria-expanded` | `video/Inspetor.tsx` |
| Faixa da linha do tempo | Bloco de 14 px na cor do tipo, 4 px entre faixas, cantos de 2 px; selecionado com anel de foco; cursor de 2 px em `foreground`; riscos de corte na régua; nome acessível com quem e quando ("Aparição de Leão Lobo, 03:31 a 04:21") (P5, P8) | `video/LinhaDoTempo.tsx`, `linhaDoTempo.ts` |
| Menu e diálogo | `popover`, borda, `shadow-float`; no diálogo, o primário à direita e o "Cancelar" ao lado. Perigo usa `Dialog` com o botão contornado | `ui/dropdown-menu.tsx`, `ui/dialog.tsx` |
| Confirmação na própria linha | A pergunta, "Cancelar" (Esc) e o botão de perigo (Enter), no próprio detalhe ou na própria linha. Remover uma ocorrência e descartar uma correção não abrem diálogo | `video/Correcao.tsx`, `video/Gaveta.tsx` |
| Dica | `Tooltip` com 300 ms de espera, o rótulo e a tecla | `ui/tooltip.tsx` |
| Atalhos | `?` abre o diálogo com a lista agrupada, tecla (`Kbd`) e ação, na ordem de [principios.md](principios.md) | `Atalhos.tsx` |
| Estado vazio | Uma frase que diz que está vazio e outra que diz o que fazer; o botão da saída quando houver (P7) | `acervo/Acervo.tsx`, `admin/comum.tsx` (`Vazio`) |
| Alerta de erro | Fundo `destructive` a 12%, ícone, a mensagem em português, o código para o suporte em cinza e "Tentar de novo" (P7) | `comum/Falha.tsx` |
| Carregando | `IconLoader2` girando e `role="status"` com o que carrega no `aria-label` (ou por escrito, no diálogo). O esqueleto do acervo fica parado, sem cintilar | `admin/comum.tsx`, `acervo/Video.tsx` |

## Gráficos

Regras e escala de cor: [seções 2.6 e 11](MAM_DESIGN_SYSTEM.md). Cada gráfico tem um botão que troca entre o gráfico e a tabela, que é a forma acessível de ler os números (P8) (`GraficoOuTabela`, `painel/pecas.tsx`). Cada gráfico tem `aria-label`.

- **Uma cor para uma série** (P3). O ranking é uma série só: barras em `primary`; a que está sob o ponteiro ou escolhida, em `link`. Nada de arco-íris por pessoa.
- **As cores de série não são as de tipo.** As de tipo foram feitas para ler como texto e são claras demais para preencher área. A divisão por tipo do Tempo de tela usa `chart-1`, `chart-2` e `chart-3`.
- **Magnitude** (a matriz marca × tipo) usa a escala sequencial `seq-100` a `seq-600`, do azul de foco: no escuro, o maior valor é o mais claro. O texto de cada passo passa no AA (o teste confere).
- **Recharts** só em `painel/pecas.tsx`. O `Ranking` de lá serve ao Painel da diretoria, ao Tempo de tela e a Marcas (as 15 maiores): barras horizontais de 16 px com 8 px entre elas, canto de 2 px na ponta. O Painel tem ainda a série no tempo em barra ou linha, com até ~90 pontos já somados pelo servidor. Sem eixo X no ranking; grade horizontal em `border`; texto de eixo em `muted-foreground`. Dica em `popover`. Os gráficos não animam (P2, P9).
- **Feito em CSS, sem biblioteca:** a divisão por tipo do Tempo de tela e a barrinha de cada linha da tabela, de até 48 px (`relatorios/comuns.tsx`).

## Onde a interface construída difere do MAM_DESIGN_SYSTEM

O MAM_DESIGN_SYSTEM descreve as três opções do protótipo; a opção B Galeria virou o `web/`, e algumas medidas mudaram no caminho. Valem as da interface construída, até alguém decidir o contrário:

- **Fontes:** só Plex Sans e Plex Mono, de `@fontsource` (`index.css`). Não há a Sans Condensed, nem a Mono 500, nem o `<link>` do Google Fonts.
- **Hachurado** em `border-strong`, não em `border` (`video/LinhaDoTempo.tsx`).
- **Acervo:** grade de cartões (4 tamanhos, de 200 a 420 px de largura mínima) ou lista de linhas de 80 px com miniatura, sem colunas e sem ordenação por coluna. Ordena por data de envio ou de exibição (`acervo/Acervo.tsx`). Os filtros (Programa, Estado, Período) ficam em linha no cabeçalho, sem painel lateral. O cartão não mostra a barra de presença nem percorre os quadros ao passar o mouse. A barra de presença existe só nas linhas de pessoa do inspetor.
- **Inspetor:** 400 px (420 a partir de `xl`), de largura fixa, sem arrastar. Abaixo de `lg` ele vira um bloco empilhado de 80% da altura da tela, não um `Sheet` (`video/Inspetor.tsx`).
- **Comparação com a passada** (toma o lugar do inspetor): ao lado do vídeo, com 62% da largura, só a partir de `xl`; de `lg` a `xl` fica embaixo do vídeo, em largura total e 45% da altura, para o cabeçalho e o transporte do vídeo não perderem largura (`video/Comparacao.tsx`). Nessa faixa o controle de volume volta à barra mesmo com a revisão ligada.
- **Placeholder dos campos da Administração** em `subtle` (`admin/comum.tsx`, `CAMPO`), abaixo do AA sobre `input`. A regra é o texto secundário; a troca está pendente.
- **Sem Data Table (TanStack Table), Sonner nem AlertDialog.** As tabelas são HTML simples. O aviso de ação é um `role="status"` na própria tela, e o diálogo de perigo é um `Dialog`.
- **Tempo de tela e Marcas** não têm mapa de calor de pessoa × vídeo. Além do ranking das 15 maiores, a tabela completa vem de 50 em 50 com cursor.
