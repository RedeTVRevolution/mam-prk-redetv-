# MAM Design System

A base visual do redesenho do MAM em Tailwind CSS e shadcn/ui: cores, fontes, bordas, espaçamento, grade, ícones e gráficos. Os três protótipos usam este arquivo e só variam a **estrutura** (seção 9); cor, tipo e forma são os mesmos nos três.

O brief:

- **Premium dark mode** de software de edição e broadcast.
- **UI densa e utilitária**, para metadado, preview de vídeo e tag.
- **Grade rígida e painéis colapsáveis.** Nada de layout assimétrico.
- **Todo menu e link tem ícone.** O texto ajuda, mas o ícone nunca falta.
- **Single page application**: a navegação troca o painel, não a página.

## 1. A ideia

O MAM vira uma **mesa de edição**: painéis encaixados lado a lado, separados por uma costura de 1 px, como num editor não linear. O fundo da aplicação só aparece nessas costuras. Nenhum painel flutua sobre o outro, salvo menu, dica e diálogo.

A ousadia fica num lugar só: **as faixas de ocorrência**. As 7 cores de tipo (pauta, aparição, menção, objeto, marca, fala, texto na tela) são a assinatura visual do produto. Elas aparecem na linha do tempo do player, na **barra de presença** sob cada miniatura do acervo, nos chips de filtro e nas abas do inspetor. Quem aprende a cor num lugar a reconhece em todos. O resto da interface é grafite, quieto.

**Herdado sem mudança** do [`sistema-visual.md`](sistema-visual.md) e dos [princípios](principios.md), porque já foi medido e testado:

- as 7 cores de tipo, buscadas sob AA e deuteranopia;
- verde, âmbar e vermelho para o estado do Job;
- o vermelho só no logotipo;
- o azul de foco `#3871DC`;
- algarismos tabulares, base de 4 px;
- nada de gradiente, brilho ou vidro, e sombra de no máximo 8 px de desfoque;
- os atalhos de teclado.

## 2. Cores

### 2.1 Superfícies e texto

Cinco degraus de grafite, levemente frios. Cada camada acima clareia um pouco. O vídeo fica cercado de cinza escuro, como numa sala de edição.

| Função | Variável shadcn | Hex | HSL | Classe Tailwind | Onde |
| --- | --- | --- | --- | --- | --- |
| `canvas` | — | `#0D0E10` | `220 10% 6%` | `bg-canvas` | Fundo da aplicação; só aparece nas costuras entre painéis e atrás do vídeo |
| `painel` | `--background`, `--sidebar` | `#141619` | `216 11% 9%` | `bg-background` | Corpo de todo painel: acervo, inspetor, filtros, trilho |
| `elevado` | `--card`, `--muted` | `#1B1E22` | `214 12% 12%` | `bg-card`, `bg-muted` | Cabeçalho de painel, cartão de mídia, linha selecionada sem foco, cabeçalho de tabela |
| `sobreposto` | `--popover`, `--accent` | `#23262B` | `218 10% 15%` | `bg-popover`, `bg-accent` | Menu, popover, dica, diálogo; hover sobre `elevado` |
| `controle` | `--input`, `--secondary` | `#2B2F35` | `216 10% 19%` | `bg-input`, `bg-secondary` | Campo, botão secundário, chip desligado, trilho do slider |
| `linha` | `--border`, `--sidebar-border` | `#2A2D33` | `220 10% 18%` | `border-border` | Toda borda de 1 px, costura entre painéis, divisória de tabela |
| `linha-forte` | — | `#3A3E45` | `218 9% 25%` | `border-strong` | Contorno de campo e chip, régua da linha do tempo |
| `texto` | `--foreground`, `--card-foreground`, `--popover-foreground` | `#E8EAED` | `216 12% 92%` | `text-foreground` | Texto principal |
| `texto-2` | `--muted-foreground` | `#A6ABB4` | `219 9% 68%` | `text-muted-foreground` | Metadado, rótulo, contagem, placeholder |
| `texto-3` | — | `#767B84` | `219 6% 49%` | `text-subtle` | Só controle desabilitado |

Contraste conferido (WCAG):

| Texto | `canvas` | `painel` | `elevado` | `sobreposto` | `controle` |
| --- | --- | --- | --- | --- | --- |
| `texto` | 16,0 | 15,0 | 13,9 | 12,6 | 11,2 |
| `texto-2` | 8,4 | 7,9 | 7,3 | 6,6 | 5,8 |
| `texto-3` | 4,5 | 4,3 | 3,9 | 3,6 | 3,2 |

O `texto-2` passa no AA em todos os fundos, então pode ser usado como placeholder. O `texto-3` é só para controle desabilitado, que a WCAG isenta (1.4.3).

### 2.2 Foco, seleção e ação principal

| Função | Variável shadcn | Hex | HSL | Classe | Onde |
| --- | --- | --- | --- | --- | --- |
| `foco` | `--primary`, `--ring`, `--sidebar-primary`, `--sidebar-ring` | `#3871DC` | `219 70% 54%` | `bg-primary`, `ring-ring` | Botão primário, anel de foco, barra do item atual, item ativo do trilho, cursor de reprodução selecionado |
| `foco-texto` | — | `#82AAF5` | `219 85% 74%` | `text-link` | Link, valor de filtro ativo |
| `selecionado` | — | `#1A2538` | `219 37% 16%` | `bg-selected` | Linha ou cartão selecionado: `foco` a 16% sobre `painel`, já misturado |
| `sobre-foco` | `--primary-foreground` | `#FFFFFF` | `0 0% 100%` | `text-primary-foreground` | Texto no botão primário: 4,6:1 |

O anel de foco tem 2 px em `foco`, com `ring-offset-2` na cor do painel, então sempre fica sobre `painel` ou `elevado` (3,9:1 e 3,6:1). **O anel nunca encosta direto em `controle`**, onde daria só 2,9:1.

O texto sobre `selecionado` tem 12,8:1, e o `texto-2`, 6,7:1.

### 2.3 Estado do Job

Cada estado tem uma cor, e o selo leva sempre o ícone e a palavra. A cor nunca é a única pista.

| Estado | Variável | Hex | Ícone (Tabler) | Estados do Job |
| --- | --- | --- | --- | --- |
| Concluído | `--ok` | `#5CC98A` | `IconCircleCheck` | Concluído |
| Em andamento | `--andamento` | `#E5B045` | `IconLoader2` (gira só enquanto decupa), `IconClock` (aguardando) | Aguardando envio, Em quarentena, Decupando |
| Falhou | `--destructive` | `#F4736A` | `IconAlertTriangle` | Falhou; também é a cor de erro e de perigo, sempre como texto, borda ou fundo a 12% |
| Inerte | `--muted-foreground` | `#A6ABB4` | `IconCircleOff` | Cancelado |

- **Selo:** texto na cor do estado, sobre a mesma cor a 12%, com raio de 2 px e 20 px de altura.
- **Botão de perigo:** contornado, com texto e borda em `--destructive` sobre o fundo do painel (6,5:1). **Nunca** a variante `destructive` do shadcn como vem (`bg-destructive text-white`): o branco sobre `#F4736A` dá 2,8:1, abaixo do AA. Troque a variante no `button.tsx` para `border border-destructive text-destructive hover:bg-destructive/12`.
- **Na miniatura:** o estado aparece como *tally*, uma faixa de 3 px na borda de cima, como a luz de câmera no estúdio. A faixa só aparece quando o vídeo **não** está concluído: o acervo pronto fica limpo, e o que pede atenção salta.

### 2.4 Marca RedeTV

| Função | Hex | Onde |
| --- | --- | --- |
| `marca` | `#E03131` | **Só no logotipo.** Na TV, vermelho quer dizer "no ar" ou erro |

### 2.5 Tipos de ocorrência

A assinatura do produto. São os mesmos valores do `tema.ts` de hoje, sem nenhuma alteração.

| Tipo | Variável | Hex | Ícone (Tabler) | Onde |
| --- | --- | --- | --- | --- |
| Pauta | `--tipo-pauta` | `#8A9CF5` | `IconListDetails` | Faixa, chip, aba do inspetor, barra de presença |
| Pessoa na imagem (aparição) | `--tipo-aparicao` | `#F5A55A` | `IconUser` | Faixa, chip, aba, barra de presença |
| Menção | `--tipo-mencao` | `#F08AAE` | `IconQuote` | Faixa, chip, aba |
| Objeto | `--tipo-objeto` | `#A0A030` | `IconBox` | Faixa, chip, aba |
| Comercial e marca | `--tipo-marca` | `#D9C2FF` | `IconBadgeTm` | Faixa, chip, aba |
| Fala | `--tipo-fala` | `#8E9196` | `IconMicrophone` | Faixa, chip, aba |
| Texto na tela | `--tipo-texto` | `#A8EFC8` | `IconTextRecognition` | Faixa, chip, aba |

- **Legíveis como texto:** as 7 passam no AA sobre `canvas`, `painel`, `elevado` e `sobreposto`, e o chip ligado escreve o nome na cor do tipo.
- **Fala em `controle`:** sobre `controle`, a fala cai para 4,3:1. Por isso, o texto de tipo nunca vai sobre `controle`.
- **Ícone junto:** na faixa, no chip e na aba, o tipo leva sempre o ícone, então a cor não é a única pista.
- **Hachurado:** o trecho sem decupagem continua hachurado em `linha`, com listras de 2 px a cada 6 px.

### 2.6 Cores de gráfico

As cores de tipo foram feitas para ler como texto, e são claras demais para preencher área. O validador da skill de dataviz reprova as 7 juntas: luminosidade fora da faixa, e a fala cinza perto da menção e da pauta. Então os gráficos usam **as mesmas famílias, ajustadas para preencher área no escuro**, com no máximo três séries por gráfico. Foram validadas sobre `painel`, em todos os pares.

| Série | Hex | Família | Onde |
| --- | --- | --- | --- |
| Aparição | `#D95926` | Laranja da aparição | Divisão por tipo no Tempo de tela |
| Menção na fala | `#C25BD6` | Rosa da menção, puxado para o violeta | Idem |
| Menção no texto da tela | `#199E70` | Verde do texto na tela | Idem |

Resultado do validador para os três (`--mode dark --surface #141619 --pairs all`): todos passam. O par mais próximo para daltônico (deuteranopia) tem ΔE 9,4, e o mínimo pedido é 8. Na visão comum, o par mais próximo passa do mínimo de 15.

**Escala sequencial** (magnitude, para o mapa de calor e a matriz marca × tipo): um tom só, o azul de foco, do claro ao escuro.

| Passo | 100 | 250 | 400 | 500 | 600 |
| --- | --- | --- | --- | --- | --- |
| Hex | `#CDE2FB` | `#86B6EF` | `#3987E5` | `#256ABF` | `#184F95` |

A escala passou nas checagens de sequência ordenada: luminosidade em ordem, passos visíveis, um tom só. No escuro, o valor maior é o mais claro. O zero é a própria superfície, sem cor.

**Série única** (ranking): `foco` (`#3871DC`); a barra sob o ponteiro vai para `foco-texto`.

## 3. Tipografia

Uma família, três cortes: **IBM Plex**.

- **Por que o IBM Plex:** tem herança de engenharia, sem o ar genérico do Inter. Tem algarismos tabulares de verdade, e a versão condensada ganha densidade sem perder leitura.
- **O custo:** uma fonte baixada, onde o sistema de hoje usa a fonte do sistema. São cerca de 90 KB em `woff2`, com `font-display: swap`.

| Corte | Família | Pesos | Uso |
| --- | --- | --- | --- |
| Interface | `IBM Plex Sans` | 400, 500, 600 | Botões, rótulos, títulos, texto corrido (transcrição, descrição de plano) |
| Dados | `IBM Plex Sans Condensed` | 400, 500, 600 | Célula de tabela, lista de metadado, item do inspetor, rótulo de eixo |
| Tempo | `IBM Plex Mono` | 400, 500 | **Só timecode e duração** (`01:12:04;15`, `48:08`) e código de erro para o suporte |

```html
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### 3.1 Escala

Base de 13 px, a medida de uma interface de edição.

| Token Tailwind | Tamanho / altura de linha | Peso | Uso |
| --- | --- | --- | --- |
| `text-2xs` | 11 / 14 px | 500 | Só rótulo de régua da linha do tempo e contagem dentro de aba |
| `text-xs` | 12 / 16 px | 400, 500 | Metadado, selo, chip, cabeçalho de seção do painel |
| `text-sm` | 13 / 18 px | 400, 500 | **Padrão.** Tabela, item de lista, botão, campo |
| `text-base` | 14 / 22 px | 400 | Texto corrido: transcrição, descrição, mensagem de diálogo |
| `text-lg` | 16 / 22 px | 600 | Título de painel e de diálogo |
| `text-xl` | 20 / 26 px | 600 | Título de página (nome do vídeo no player, nome do relatório) |

Regras:

- **Peso:** 600 no máximo. O 700 "acende" demais no escuro.
- **Algarismos:** `tabular-nums` em todo número, tempo e contagem: colunas alinhadas, e o relógio não "dança".
- **Caixa:** frase normal sempre. **Nada de caixa alta** em rótulo, aba ou cabeçalho.
- **Linha:** texto corrido com até 72 caracteres. A transcrição no inspetor tem de 48 a 60, pela largura do painel.
- **Corte:** com reticências (`truncate`) e o texto inteiro na dica. Nome de arquivo nunca quebra de linha.

## 4. Espaçamento

Base de 4 px, a mesma unidade do Tailwind (`1` = 4 px). Só estes passos entram:

| Classe | Valor | Uso |
| --- | --- | --- |
| `0.5` | 2 px | Vão entre blocos encostados na faixa; dentro de selo |
| `1` | 4 px | Entre ícone e rótulo; entre chips |
| `2` | 8 px | Dentro de componente; padding de célula na horizontal |
| `3` | 12 px | Padding do corpo do painel; entre grupos |
| `4` | 16 px | Entre blocos de um painel; margem do diálogo |
| `6` | 24 px | Entre seções de relatório |
| `8` | 32 px | Só o estado vazio, centralizado |

`5`, `7` e qualquer valor fora da escala são proibidos. Se não cabe, a medida está errada.

## 5. Densidade e medidas fixas

| Peça | Medida | Classe |
| --- | --- | --- |
| Barra superior | 40 px | `h-10` |
| Cabeçalho de painel | 32 px | `h-8` |
| Linha de tabela, compacta | 28 px | `h-7` |
| Linha de tabela, padrão | 32 px | `h-8` |
| Linha de tabela com miniatura | 48 px (miniatura de 64 × 36) | `h-12` |
| Botão e campo em barra de ferramenta | 28 px | `h-7` |
| Botão e campo em formulário | 32 px | `h-8` |
| Botão de ícone | 28 × 28 px (alvo), ícone de 16 | `size-7` |
| Item do trilho | 40 × 40 px, ícone de 20 | `size-10` |
| Faixa da linha do tempo | 14 px, com 4 px entre faixas | `h-3.5` |
| Barra de presença sob a miniatura | 4 px | `h-1` |
| Tally de estado | 3 px | `h-[3px]` |

Na linha padrão, **30 vídeos cabem sem rolar** em 1080 px: 40 da barra superior, mais 32 do cabeçalho, mais 30 × 32 das linhas, dá 1032 px.

## 6. Forma: bordas, raios e sombras

### 6.1 Bordas

- **1 px em todo lugar**, em `linha`. Contorno de campo e de chip em `linha-forte`.
- **Costura:** painéis encaixados não têm borda própria nem vão. Entre eles fica uma costura de 1 px (`gap-px bg-canvas`, ou `border-r border-border`).
- **Nada de borda dupla:** quando dois elementos encostam, só um tem a borda.

### 6.2 Raios

O raio diz a hierarquia: quanto menor a peça, menor o canto.

| Token Tailwind v4 | Valor | Onde |
| --- | --- | --- |
| `rounded-none` | 0 | Painel encaixado, cabeçalho de painel, tabela, miniatura dentro da linha |
| `rounded-xs` | 2 px | Bloco da linha do tempo, selo, tally, barra de gráfico na ponta |
| `rounded-sm` | 4 px | Botão, campo, chip, item do trilho, cartão de mídia |
| `rounded-md` | 6 px | Menu, popover, dica, diálogo: o que flutua |

`rounded-lg` e acima são **proibidos**.

O shadcn usa `--radius`. Ponha `--radius: 6px` e mapeie `--radius-xs: 2px`, `--radius-sm: 4px` e `--radius-md: 6px`, como na seção 15; `--radius-lg` e acima também ficam em 6 px, para nenhum componente do shadcn passar disso. O `Card` do shadcn v4 vem com `rounded-xl`: troque para `rounded-sm`.

### 6.3 Sombra e profundidade

- **Separação:** o que é encaixado se separa pela cor, sem sombra.
- **O que flutua** (menu, popover, dica, diálogo) usa uma sombra só: `shadow-[0_4px_8px_rgb(0_0_0/0.45)]`, mais a borda de 1 px em `linha`.
- **Proibido:** gradiente, brilho, `backdrop-blur`, sombra colorida, borda luminosa.
- **Fundo do diálogo:** `bg-black/60`, chapado.

## 7. Ícones

Um conjunto só: **Tabler Icons** (`@tabler/icons-react`, já instalado). Contorno com `stroke={1.75}`.

| Tamanho | Onde |
| --- | --- |
| 16 px | Na linha da tabela, no botão de ícone, no chip, no selo, na aba do inspetor |
| 20 px | Trilho de navegação, barra superior, transporte do player |

**Regra:** todo menu, link e botão de ícone tem rótulo.

- **Visível:** o trilho aberto, um botão com texto ou uma aba com nome.
- **Sem texto à vista:** o `Tooltip` do shadcn mostra o rótulo depois de 300 ms, ao lado do atalho de teclado, e o `aria-label` repete o rótulo.
- **Nunca:** um ícone sozinho sem nome acessível.

### 7.1 Mapa de navegação

| Destino | Ícone | Atalho |
| --- | --- | --- |
| Acervo | `IconMovie` | `G` `A` |
| Busca | `IconSearch` | `/` |
| Enviar vídeo | `IconCloudUpload` | `U` |
| Relatório de tempo de tela | `IconUserScan` | `G` `T` |
| Relatório de marcas | `IconBadgeTm` | `G` `M` |
| Painel da diretoria | `IconChartBar` | `G` `P` |
| Administração | `IconSettings` | `G` `D` |
| › Entradas | `IconInbox` | |
| › Usuários | `IconUsers` | |
| › Sistemas e chaves | `IconKey` | |
| › Regras de aprovação | `IconChecklist` | |
| › Programas | `IconBroadcast` | |
| › Lixeira | `IconTrash` | |
| › Auditoria | `IconHistory` | |
| Atalhos de teclado | `IconKeyboard` | `?` |
| Conta | Avatar com a inicial | |

### 7.2 Ações frequentes

| Ação | Ícone |
| --- | --- |
| Tocar | `IconPlayerPlay` |
| Pausar | `IconPlayerPause` |
| Baixar | `IconDownload` |
| Reprocessar | `IconRefresh` |
| Quem acessou | `IconEye` |
| Histórico | `IconHistory` |
| Mais ações | `IconDots` |
| Filtros | `IconFilter` |
| Exibir em lista | `IconList` |
| Exibir em grade | `IconLayoutGrid` |
| Recolher painel | `IconLayoutSidebarLeftCollapse` |
| Recolher inspetor | `IconLayoutSidebarRightCollapse` |
| Ver tabela | `IconTable` |
| Ver gráfico | `IconChartBar` |
| Copiar link no tempo atual | `IconLink` |
| Seguir a reprodução | `IconFocus2` |

## 8. Grade e painéis

### 8.1 A casca da aplicação

A casca nunca muda. A navegação troca só a área de trabalho.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▣ RedeTV MAM   [⌕ Buscar no acervo…                       /]   ⚙ (B) │ 40 px
├────┬─────────────────────────────────────────────────────────────────┤
│ ⬚  │                                                                 │
│ ⬚  │                                                                 │
│ ⬚  │                        área de trabalho                         │
│ ⬚  │             (painéis encaixados, com costura de 1 px)           │
│ ⬚  │                                                                 │
│    │                                                                 │
│ ⬚  │                                                                 │
└────┴─────────────────────────────────────────────────────────────────┘
 48 px fechado / 208 px aberto
```

| Região | Medida | Comportamento |
| --- | --- | --- |
| Barra superior | 40 px, a largura toda | Logotipo, busca global (abre a paleta de comandos), botão de envio, conta |
| Trilho de navegação | 48 px fechado, 208 px aberto | `Sidebar` do shadcn com `collapsible="icon"`. Começa fechado; `[` alterna; o estado fica salvo |
| Painel de filtros | 280 px | Recolhível (`IconFilter`). Recolhido, vira uma coluna de 40 px com o ícone e a contagem de filtros ativos |
| Área principal | O resto, no mínimo 560 px | Tabela, grade de mídia ou player |
| Inspetor | 384 px; arrastável de 320 a 480 | `ResizablePanel`, recolhível (`IconLayoutSidebarRightCollapse`, tecla `]`) |

### 8.2 Regras da grade

- **Simétrica e rígida.** As colunas do painel têm largura fixa ou fração inteira. Nada de bento, de cartão com o dobro do tamanho ou de coluna deslocada.
- **Grade de mídia:** colunas iguais, `grid-cols-[repeat(auto-fill,minmax(var(--card),1fr))]`. O `--card` vem de 4 passos (160, 200, 240 e 320 px), escolhidos num `Slider`, como no iconik. Todo cartão tem a mesma altura.
- **Alinhamento:** tudo à esquerda. Número e tempo à direita, na coluna. Nada centralizado, salvo o estado vazio.
- **Painéis colapsáveis:**
  - todo painel lateral recolhe para uma coluna de 40 px com o ícone dele, sem sumir;
  - o painel aberto e a largura ficam salvos por usuário;
  - a animação é a largura em 150 ms, desligada com `prefers-reduced-motion`.
- **O vídeo nunca sai da tela.** No player, só o inspetor e a lista rolam (P4).

### 8.3 Pontos de quebra

| Largura | Comportamento |
| --- | --- |
| ≥ 1440 px | Tudo aberto: trilho, filtros, área principal, inspetor |
| 1280–1439 px | O painel de filtros começa recolhido |
| 1024–1279 px | O inspetor vira `Sheet` sobre a área principal |
| < 1024 px | Uma coluna só. O trilho vira barra inferior de ícones, e os filtros viram `Sheet` |

## 9. As três opções

As três usam o mesmo sistema. Só a estrutura muda.

### Opção A: Console

A tabela é a estrela, como num gerenciador de mídia de redação.

```
┌──┬──────────┬──────────────────────────────────────────────┐
│≡ │ Filtros  │ ▤ ▦  Ordenar ▾   30 de 1.204                 │
│  │ ▸ Estado │──────────────────────────────────────────────│
│  │ ▸ Progr. │ ▭ nome.mp4   TV Fama  12/10  49:19  ● Concl. │
│  │ ▸ Data   │ ▭ nome.mp4   —        —      31:00  ● Concl. │
│  │ ▸ Pessoa │ ▭ …                                          │
└──┴──────────┴──────────────────────────────────────────────┘
```

- **Acervo:** `Data Table` com miniatura de 64 × 36, barra de presença, colunas fixas, ordenação, seleção em lote e ações por linha.
- **Filtros:** acordeões no painel lateral.
- **Player:** vídeo à esquerda, inspetor à direita com **abas verticais de ícones** na borda, como os painéis de um editor.

### Opção B: Galeria (a referência do iconik)

A imagem é a estrela.

```
┌──┬──────────┬──────────────────────────────────────────────┐
│≡ │ Filtros ✕│ Acervo  1.204   Ordenar ▾   ─●── ▤ ▦         │
│  │ Pessoa ▾ │┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐      │
│  │ Marca  ▾ ││ img  ││ img  ││ img  ││ img  ││ img  │      │
│  │ Progr. ▾ │├══════┤├══════┤├══════┤├══════┤├══════┤ pres.│
│  │ Estado ▾ ││nome ⋮││nome ⋮││nome ⋮││nome ⋮││nome ⋮│      │
│  │ Data     │└──────┘└──────┘└──────┘└──────┘└──────┘      │
└──┴──────────┴──────────────────────────────────────────────┘
```

- **Acervo:** grade de cartões 16:9, com tamanho ajustável. Passar o mouse percorre os quadros do vídeo. A barra de presença fica sob a imagem; nome, duração e ações embaixo.
- **Filtros:** um `Combobox` com contagem por valor, como no iconik.
- **Player:** o inspetor em seções `Collapsible`: Agora, Pessoas, Marcas, Objetos, Pautas, Textos e Fala.

### Opção C: Estação

Tudo numa tela só, como num editor não linear.

```
┌──┬────────────┬───────────────────────────┬───────────────┐
│≡ │ Acervo     │                           │ Inspetor      │
│  │ ▭ nome     │          vídeo            │ Agora         │
│  │ ▭ nome  ◀  │                           │ Pessoas (25)  │
│  │ ▭ nome     │                           │ …             │
│  │            ├───────────────────────────┴───────────────┤
│  │            │ ▬▬ pauta  ▬ ▬▬ pessoas  ▬ objetos … régua │
└──┴────────────┴───────────────────────────────────────────┘
```

- **Acervo:** a lista de vídeos fica sempre à esquerda. Clicar troca o vídeo sem sair da tela.
- **Linha do tempo:** embaixo, na largura toda, com as faixas que se escondem ou mostram uma a uma.
- **Inspetor:** à direita.
- **Painéis:** todos `Resizable`.

## 10. O player e o inspetor (os três)

O painel direito de hoje mistura o momento atual, as abas e a lista numa coluna só. O inspetor novo tem uma ordem fixa:

```
┌ Inspetor ─────────────────────────── ⟲  ]  ┐ 32 px, cabeçalho
│ Agora · 12:34                               │ seção fixa, recolhível
│  ┌──┐┌──┐┌──┐  Leão Lobo, Nelson Rubens     │ rostos de quem está na tela
│  └──┘└──┘└──┘  Objeto: microfone azul       │
│  "Hoje no TV Fama…"            (fala atual) │
├─────────────────────────────────────────────┤
│ [⌕ Filtrar…]  ⦿ Seguir a reprodução         │ 32 px, fixo
├─────────────────────────────────────────────┤
│ 12:31  ● Leão Lobo         aparição         │ lista, a única parte
│ 12:34  ● Nelson Rubens     aparição    ◀ atual   que rola
│ …                                           │
└─────────────────────────────────────────────┘
```

- **Agora:** o que está na tela no tempo do cursor, em uma linha por tipo, com o ícone e a cor dele. Clicar em um item filtra a lista por ele.
- **Tipos:** cada tipo é uma aba com ícone, cor e contagem (zero aparece como zero). Na opção A, as abas ficam verticais na borda; na B, viram seções; na C, chips no topo da lista.
- **Seguir a reprodução:** ligado, a lista acompanha o vídeo. O item atual tem a barra de 3 px em `foco` e fundo `elevado`. Rolar à mão desliga o seguir, e um botão "Voltar ao tempo atual" aparece.
- **Detalhe:** clicar no item abre o detalhe no próprio inspetor, sem diálogo: evidência (GC, fala ou rosto), tempo, confiança e as ações de correção. `Esc` volta à lista.
- **Ações do vídeo:** reprocessar, baixar, histórico e quem acessou ficam na barra de cima do player, como botões de ícone com dica. Saem do inspetor.

## 11. Gráficos e relatórios

Base: `Chart` do shadcn (Recharts), com estas regras:

- **Forma antes da cor.** Ranking é barra horizontal de uma série. Composição por tipo é barra empilhada de 100%. Presença no tempo é mapa de calor (sequencial). Evolução por dia (#349) é linha.
- **Sem lista de 200 barras.** O ranking mostra as 15 maiores. O resto fica na `Data Table` embaixo, com uma minibarra dentro da célula. A tabela é também a forma acessível de ler os números.
- **Barra:** 16 px de altura, 4 px de vão, raio de 2 px só na ponta (a base encosta no eixo).
- **Rótulo e valor:** o nome à esquerda; o valor na ponta, em `texto-2` e algarismos tabulares.
- **Eixos e grade:** sem eixo X. A grade, quando existe, é de 1 px em `linha`.
- **Cor das séries:** só as da seção 2.6. **O texto nunca usa a cor da série**: rótulo e valor ficam em `texto` e `texto-2`, e a marca colorida ao lado dá a identidade.
- **Legenda:** a partir de duas séries, sempre há legenda, e até quatro séries também têm rótulo direto. Uma série só não tem legenda; o título a nomeia.
- **Interação:** dica ao passar o mouse em toda barra e célula, em `sobreposto`, com o nome em 600 e os números tabulares. Clicar numa barra filtra a tabela e abre o recorte.
- **Filtros:** numa linha só acima dos gráficos: programa, período e tipo. A troca de filtro **não repinta** quem continua na tela, porque a cor segue a série.
- **Movimento:** nada anima o crescimento das barras.
- **Alternância:** toda visualização tem o botão `IconTable`/`IconChartBar` para trocar entre gráfico e tabela.

**Tempo de tela:** ranking das 15 pessoas; ao lado, a composição da escolhida (aparição, menção na fala, menção no texto); embaixo, o mapa de calor de pessoa × vídeo e a tabela completa.

**Marcas:** ranking das marcas por tempo; a matriz marca × tipo de inserção como mapa de calor na escala sequencial, com o valor escrito na célula; a tabela com os vídeos de cada marca.

## 12. Componentes shadcn/ui

| Necessidade | Componente | Ajuste ao sistema |
| --- | --- | --- |
| Trilho de navegação | `Sidebar` (`collapsible="icon"`) | 48/208 px; item de 40 px; ativo com barra de 3 px em `foco` |
| Acervo e tabelas | `Data Table` (TanStack Table) | Linhas de 28, 32 ou 48 px; cabeçalho fixo; colunas fixas; `aria-sort` |
| Preview de mídia | `Card` + `AspectRatio` (16/9) + `HoverCard` | `rounded-sm`; percorre os quadros ao passar o mouse; tally e barra de presença |
| Busca global e atalhos | `Command` (paleta em `⌘K` e `/`) | Grupos: vídeos, pessoas, marcas, ações |
| Filtros por faceta | `Combobox` (`Popover` + `Command`) com seleção múltipla | Contagem por valor à direita, em `texto-2` |
| Painéis | `Resizable` e `Collapsible` | Costura de 1 px; recolhe para 40 px |
| Seções do inspetor | `Accordion` (B) e `Tabs` verticais (A) | Cabeçalho de 32 px, ícone, contagem |
| Alternar a exibição | `ToggleGroup` | Lista, grade, tamanho do cartão |
| Tamanho do cartão | `Slider` | 4 passos |
| Datas | `Popover` + `Calendar` | Intervalo "exibido de / até" |
| Estado e tipo | `Badge` | Variantes de estado e de tipo |
| Dica | `Tooltip` | 300 ms; rótulo e atalho |
| Menus | `DropdownMenu` e `ContextMenu` | Clique direito na linha ou no cartão abre as mesmas ações do `⋮` |
| Diálogo | `Dialog` e `AlertDialog` | Perigo sempre em `AlertDialog`, com o botão de perigo contornado (2.3) |
| Painel no celular | `Sheet` | Filtros e inspetor abaixo de 1024 px |
| Aviso | `Sonner` | Em baixo, à direita; ação desfazer quando houver |
| Carregando | `Skeleton` | Na forma do conteúdo; sem cintilar |
| Gráficos | `Chart` (Recharts) | Seção 11 |
| Tecla | `Kbd` | Na dica e na lista do `?` |

### 12.1 Peças do Aceternity UI que cabem

O [Aceternity UI](https://ui.aceternity.com/components) entra como inspiração, sempre sem gradiente, brilho ou fundo animado:

- **`Sidebar`:** trilho que abre ao passar o mouse; o mesmo comportamento do `Sidebar` do shadcn em `collapsible="icon"`.
- **`Floating Dock`:** a ideia de ícone com rótulo que aparece ao passar o mouse, aplicada ao transporte do player. Sem o efeito de lupa.
- **`File Upload`:** a área de arrastar do envio de vídeo, com a lista de arquivos e o andamento.
- **`Expandable Card`:** o cartão de mídia que abre o resumo do vídeo sem sair do acervo.
- **`Animated Tooltip`:** a fila de rostos de quem aparece no vídeo, no cartão e no "Agora".
- **`Placeholders And Vanish Input`:** só a parte dos exemplos de busca que se alternam no campo vazio ("Leão Lobo no estúdio", "Ultrafarma"), sem o efeito de sumir.
- **`Stateful Button`:** reprocessar e salvar mostram o andamento e o resultado no próprio botão.

**Ficam de fora**, porque contrariam o brief ou a regra de nada de gradiente:

- fundos animados (aurora, feixes, estrelas, ondas);
- `Bento Grid`, por ser assimétrico;
- cartões 3D, de brilho ou de holofote;
- texto animado.

## 13. Movimento

- **Duração:** 150 ms, com `ease-out`.
- **O que anima:** abrir e recolher painel, menu, popover e diálogo.
- **O que não anima:** nada se mexe sozinho. O único elemento que gira é o ícone de "Decupando".
- **Movimento reduzido:** com `prefers-reduced-motion`, tudo vira troca imediata.

## 14. O que muda em relação ao sistema de hoje

Decisões a confirmar; viram um ADR quando o redesenho for aprovado.

| Hoje (`sistema-visual.md`, princípios) | Neste sistema | Por quê |
| --- | --- | --- |
| Mantine e `@mantine/charts` (P9) | Tailwind v4, shadcn/ui e Recharts | Pedido do redesenho: componentes do shadcn, protótipos em Tailwind |
| Fonte do sistema | IBM Plex (Sans, Sans Condensed e Mono), baixada | Identidade e densidade; algarismos tabulares de verdade |
| 3 fundos | 5 (`canvas`, `painel`, `elevado`, `sobreposto`, `controle`) | Painéis encaixados precisam da costura e de mais um degrau para o controle |
| Texto padrão de 14 px; tabela de 13 | Padrão de 13 px; texto corrido de 14 | Densidade de software de edição |
| Linha de tabela de 32 px | 28, 32 ou 48 px (compacta, padrão, com miniatura) | Densidade e miniatura no acervo |
| Raio de 4 a 6 px | De 0 a 6 px por hierarquia; painel encaixado com 0 | A mesa de edição: painel reto, peça pequena arredondada |
| Menus em texto | Ícone sempre, com rótulo visível ou dica | Pedido do redesenho |
| Gráfico com as cores de tipo | As mesmas famílias ajustadas para área (2.6), validadas | As cores de tipo reprovam como preenchimento |
| Acervo só em tabela (P1: tabela antes de cartão) | Tabela (A) ou grade de cartões (B) | A referência do iconik. A opção A mantém o P1 |

Continuam valendo: as cores de tipo e de estado, o vermelho só no logotipo, o azul de foco, nenhum gradiente, sombra de no máximo 8 px, os atalhos de teclado e o AA em todo texto.

## 15. Tokens para o Tailwind v4

```css
@import "tailwindcss";

@theme inline {
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;
  --font-condensed: "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;

  --text-2xs: 11px;  --text-2xs--line-height: 14px;
  --text-xs: 12px;   --text-xs--line-height: 16px;
  --text-sm: 13px;   --text-sm--line-height: 18px;
  --text-base: 14px; --text-base--line-height: 22px;
  --text-lg: 16px;   --text-lg--line-height: 22px;
  --text-xl: 20px;   --text-xl--line-height: 26px;

  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 6px;

  --color-canvas: #0D0E10;
  --color-background: #141619;
  --color-card: #1B1E22;
  --color-muted: #1B1E22;
  --color-popover: #23262B;
  --color-accent: #23262B;
  --color-input: #2B2F35;
  --color-secondary: #2B2F35;
  --color-border: #2A2D33;
  --color-strong: #3A3E45;
  --color-foreground: #E8EAED;
  --color-card-foreground: #E8EAED;
  --color-popover-foreground: #E8EAED;
  --color-accent-foreground: #E8EAED;
  --color-secondary-foreground: #E8EAED;
  --color-muted-foreground: #A6ABB4;
  --color-subtle: #767B84;
  --color-primary: #3871DC;
  --color-primary-foreground: #FFFFFF;
  --color-ring: #3871DC;
  --color-link: #82AAF5;
  --color-selected: #1A2538;
  --color-destructive: #F4736A;
  --color-ok: #5CC98A;
  --color-andamento: #E5B045;
  --color-marca: #E03131;

  --color-sidebar: #141619;
  --color-sidebar-foreground: #E8EAED;
  --color-sidebar-primary: #3871DC;
  --color-sidebar-primary-foreground: #FFFFFF;
  --color-sidebar-accent: #23262B;
  --color-sidebar-accent-foreground: #E8EAED;
  --color-sidebar-border: #2A2D33;
  --color-sidebar-ring: #3871DC;

  --color-tipo-pauta: #8A9CF5;
  --color-tipo-aparicao: #F5A55A;
  --color-tipo-mencao: #F08AAE;
  --color-tipo-objeto: #A0A030;
  --color-tipo-marca: #D9C2FF;
  --color-tipo-fala: #8E9196;
  --color-tipo-texto: #A8EFC8;

  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-seq-100: #CDE2FB;
  --color-seq-250: #86B6EF;
  --color-seq-400: #3987E5;
  --color-seq-500: #256ABF;
  --color-seq-600: #184F95;

  --shadow-float: 0 4px 8px rgb(0 0 0 / 0.45);
}

:root {
  color-scheme: dark;
  --radius: 6px;
  /* Os exemplos do Chart do shadcn leem var(--chart-N) direto. */
  --chart-1: #D95926; /* aparição */
  --chart-2: #C25BD6; /* menção na fala */
  --chart-3: #199E70; /* menção no texto da tela */
}

body {
  background: var(--color-canvas);
  color: var(--color-foreground);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}
```

Os nomes seguem o shadcn (`background`, `card`, `popover`, `primary`, `muted`, `accent`, `destructive`, `border`, `input`, `ring`, `sidebar-*`, `chart-*`), então os componentes dele recebem o tema sem ajuste. As exceções são duas. Os gráficos leem `--chart-N` direto, e por isso essas variáveis ficam em `:root`. O botão `destructive` precisa da troca descrita em 2.3. Os nomes do MAM (`canvas`, `selected`, `tipo-*`, `ok`, `andamento`) vêm acrescentados.
