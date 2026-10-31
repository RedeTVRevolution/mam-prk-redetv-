import { Badge, Box, Group, Stack, Text, UnstyledButton, Button } from '@mantine/core'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useAtalhos } from './atalhos.ts'
import { type Intervalo, relogio } from './linhaDoTempo.ts'
import {
  ABAS,
  type Aba,
  agora,
  contem,
  deltaDeRolagem,
  deltaParaUmTerco,
  type ItemDoPainel,
  itensDaAba,
  itensDoPainel,
  NAO_IDENTIFICADO,
  semDecupagemEm,
  type Selo,
  textoDoSemDecupagem,
  TIPOS_DO_AGORA,
  type TipoDoItem,
  vizinhoNoPainel,
} from './painel.ts'
import { CORES, CORES_DE_OCORRENCIA } from './tema.ts'
import type { Decupagem } from './Video.tsx'

/** Depois que a pessoa rola o painel, ele não anda sozinho por este tempo. */
const PAUSA_DA_ROLAGEM_MS = 5000

const GRUPO = 'Painel'

const COR_DO_TIPO: Record<TipoDoItem, string> = {
  pauta: CORES_DE_OCORRENCIA.pauta.cor,
  aparicao: CORES_DE_OCORRENCIA.aparicao.cor,
  mencao: CORES_DE_OCORRENCIA.mencao.cor,
  comercial: CORES_DE_OCORRENCIA.comercial.cor,
  texto: CORES_DE_OCORRENCIA.texto_na_tela.cor,
  plano: CORES.textoSecundario,
  fala: CORES_DE_OCORRENCIA.fala.cor,
}

const TITULO_DO_TIPO: Partial<Record<TipoDoItem, string>> = {
  aparicao: 'Pessoas na imagem',
  mencao: 'Menções',
  comercial: 'Comerciais',
  texto: 'Textos na tela',
}

const VAZIO_DA_ABA: Record<Exclude<Aba, 'agora'>, string> = {
  pessoas: 'Nenhuma pessoa neste vídeo.',
  pautas: 'Nenhuma pauta neste vídeo.',
  comerciais: 'Nenhum comercial neste vídeo.',
  textos: 'Nenhum texto na tela neste vídeo.',
  planos: 'Nenhum plano neste vídeo.',
  transcricao: 'Este vídeo não tem transcrição.',
}

// Item selecionado: o azul de foco a 16% (0x29). Item atual: a barra de 3 px e o fundo elevado.
const SELECIONADO = { background: `${CORES.foco}29` }
const ATUAL = { background: CORES.elevada, boxShadow: `inset 3px 0 0 ${CORES.foco}` }

const tempos = (i: Intervalo): string => `${relogio(i.inicio_ms)}–${relogio(i.fim_ms)}`

/** O texto de apoio da linha do cabeçalho fixo, ou `null` quando não há o que dizer. */
function Cabecalho({
  itens,
  pautas,
  duracaoMs,
  atualMs,
}: {
  itens: ItemDoPainel[]
  pautas: ItemDoPainel[]
  duracaoMs: number
  atualMs: number
}) {
  const pauta = pautas.find((p) => contem(p, atualMs))
  const plano = itens.find((i) => i.tipo === 'plano' && contem(i, atualMs))
  const vazio = pauta ? null : semDecupagemEm(pautas, duracaoMs, atualMs)
  return (
    <Stack gap={2} role="group" aria-label="Momento atual">
      <Text fw={600} style={{ fontVariantNumeric: 'tabular-nums' }}>{`Agora · ${relogio(atualMs)}`}</Text>
      {pauta && <Text size="sm">{pauta.rotulo ? `${pauta.titulo} · ${pauta.rotulo}` : pauta.titulo}</Text>}
      {vazio && (
        <Text size="sm" c="dimmed">
          {textoDoSemDecupagem(vazio)}
        </Text>
      )}
      {plano && (
        <Text size="sm" c="dimmed">
          {plano.linhas[0] ? `${plano.titulo}, ${plano.linhas[0]}` : plano.titulo}
        </Text>
      )}
    </Stack>
  )
}

function SeloDaProva({ selo, aoSaltar }: { selo: Selo; aoSaltar: (ms: number) => void }) {
  if (selo.inicio_ms === null) return <Badge size="sm">{selo.rotulo}</Badge>
  const inicio = selo.inicio_ms
  return (
    <Badge
      size="sm"
      component="button"
      type="button"
      style={{ cursor: 'pointer' }}
      onClick={() => aoSaltar(inicio)}
    >
      {`${selo.rotulo} ${relogio(inicio)}`}
    </Badge>
  )
}

function Item({
  item,
  atual,
  selecionado,
  aoClicar,
  aoSaltar,
  aoReproduzir,
}: {
  item: ItemDoPainel
  atual: boolean
  selecionado: boolean
  aoClicar: (i: ItemDoPainel) => void
  aoSaltar: (ms: number) => void
  aoReproduzir: (i: ItemDoPainel) => void
}) {
  const resumo = item.tipo === 'pauta' && item.detalhe
  return (
    <Box
      data-chave={item.chave}
      aria-current={atual ? 'true' : undefined}
      p="xs"
      style={{ borderRadius: 'var(--mantine-radius-sm)', ...(atual ? ATUAL : {}), ...(selecionado ? { background: SELECIONADO.background } : {}) }}
    >
      <UnstyledButton
        data-item
        aria-label={
          item.tipo === 'fala'
            ? `${item.linhas[0] ? `${item.linhas[0]}: ` : ''}${item.titulo}, ${relogio(item.inicio_ms)}`
            : `${item.titulo}, ${relogio(item.inicio_ms)} a ${relogio(item.fim_ms)}`
        }
        aria-pressed={selecionado}
        onClick={() => aoClicar(item)}
        style={{ display: 'block', width: '100%', textAlign: 'left' }}
      >
        {item.tipo === 'fala' ? (
          // Na transcrição a linha é o início, o locutor (quando houver) e o texto inteiro.
          <Group gap="sm" wrap="nowrap" align="flex-start">
            <Text size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums', flex: 'none', paddingTop: 2 }}>
              {relogio(item.inicio_ms)}
            </Text>
            <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
              {item.linhas[0] && (
                <Text size="xs" c="dimmed">
                  {item.linhas[0]}
                </Text>
              )}
              <Text size="sm">{item.titulo}</Text>
            </Stack>
          </Group>
        ) : (
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Box
              aria-hidden
              style={{ width: 8, height: 8, marginTop: 6, flex: 'none', background: COR_DO_TIPO[item.tipo], borderRadius: 'var(--mantine-radius-xs)' }}
            />
            <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
              <Group gap="xs" wrap="nowrap" justify="space-between" align="baseline">
                <Text size="sm" style={{ minWidth: 0 }}>
                  {item.tipo === 'texto' && item.rotulo ? (
                    <>
                      <Text span size="sm" c="dimmed" fw={600}>
                        {item.rotulo}
                      </Text>
                      {'  '}
                    </>
                  ) : null}
                  {item.titulo}
                </Text>
                <Text size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums', flex: 'none' }}>
                  {tempos(item)}
                </Text>
              </Group>
              {item.rotulo && item.tipo !== 'texto' && (
                <Text size="xs" c="dimmed">
                  {item.rotulo}
                </Text>
              )}
              {item.linhas.map((l, i) =>
                resumo && i === 0 ? (
                  <Text key={l} size="xs" c="dimmed" lineClamp={selecionado ? undefined : 2}>
                    {l}
                  </Text>
                ) : (
                  <Text key={l} size="xs" c="dimmed">
                    {l}
                  </Text>
                ),
              )}
            </Stack>
          </Group>
        )}
      </UnstyledButton>
      {(item.selos.length > 0 || selecionado) && (
        <Group gap="xs" mt={4} ml={16}>
          {item.selos.map((s) => (
            <SeloDaProva key={s.rotulo} selo={s} aoSaltar={aoSaltar} />
          ))}
          {selecionado && (
            <Button size="compact-xs" variant="default" onClick={() => aoReproduzir(item)}>
              Reproduzir trecho
            </Button>
          )}
        </Group>
      )}
    </Box>
  )
}

function Secao({ titulo, children }: { titulo?: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      {titulo && (
        <Text size="xs" c="dimmed" fw={600} style={{ textTransform: 'uppercase' }}>
          {titulo}
        </Text>
      )}
      {children}
    </Stack>
  )
}

/** O painel do Visualizador: o momento atual no topo e as listas por tipo em abas. */
export function Painel({
  decupagem,
  duracaoMs,
  atualMs,
  aba,
  aoTrocarAba,
  selecionada,
  pessoasAbertas,
  aoAbrirPessoa,
  aoSelecionar,
  aoSaltar,
  aoReproduzir,
}: {
  decupagem: Decupagem
  duracaoMs: number
  atualMs: number
  aba: Aba
  aoTrocarAba: (a: Aba) => void
  selecionada: string | null
  /** As pessoas com a lista de aparições aberta. */
  pessoasAbertas: ReadonlySet<string>
  aoAbrirPessoa: (id: string) => void
  /** Seleciona sem saltar o player. */
  aoSelecionar: (chave: string) => void
  aoSaltar: (ms: number) => void
  aoReproduzir: (i: Intervalo) => void
}) {
  const itens = useMemo(() => itensDoPainel(decupagem), [decupagem])
  const pautas = useMemo(() => itensDaAba(itens, 'pautas'), [itens])
  const rolagem = useRef<HTMLDivElement>(null)
  const ultimaRolagem = useRef(0)

  const selecionado = itens.find((i) => i.chave === selecionada)
  const pessoaSelecionada = selecionado?.pessoa

  // A aparição selecionada (na linha do tempo, por exemplo) abre a lista da pessoa, que depois fecha no clique.
  const abertaPelaSelecao = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (pessoaSelecionada === abertaPelaSelecao.current) return
    abertaPelaSelecao.current = pessoaSelecionada
    if (pessoaSelecionada && !pessoasAbertas.has(pessoaSelecionada)) aoAbrirPessoa(pessoaSelecionada)
  }, [pessoaSelecionada, pessoasAbertas, aoAbrirPessoa])

  const { aparicoes, mencoes } = useMemo(() => {
    const daAba = itensDaAba(itens, 'pessoas')
    return { aparicoes: daAba.filter((i) => i.tipo === 'aparicao'), mencoes: daAba.filter((i) => i.tipo === 'mencao') }
  }, [itens])
  const pessoas = useMemo(() => decupagem.pessoas.filter((p) => p.na_imagem.length > 0), [decupagem])

  const contagens: Record<Exclude<Aba, 'agora'>, number> = {
    pessoas: pessoas.length,
    pautas: pautas.length,
    comerciais: itensDaAba(itens, 'comerciais').length,
    textos: itensDaAba(itens, 'textos').length,
    planos: itensDaAba(itens, 'planos').length,
    transcricao: itensDaAba(itens, 'transcricao').length,
  }

  // Os itens que as setas percorrem, na ordem em que aparecem na aba.
  const navegaveis = useMemo(() => {
    if (aba === 'agora') return agora(itens, atualMs)
    if (aba === 'pessoas') {
      // Como na tela: as aparições agrupadas por pessoa (só as abertas), depois as menções.
      const abertas = pessoas
        .filter((p) => pessoasAbertas.has(p.id))
        .flatMap((p) => aparicoes.filter((i) => i.pessoa === p.id))
      return [...abertas, ...mencoes]
    }
    return itensDaAba(itens, aba)
  }, [aba, itens, atualMs, pessoasAbertas, pessoas, aparicoes, mencoes])

  const chaveAtual = navegaveis.find((i) => contem(i, atualMs))?.chave

  function mostrar(chave: string, noTerco: boolean) {
    const area = rolagem.current
    const el = area?.querySelector<HTMLElement>(`[data-chave="${chave}"]`)
    if (!area || !el) return
    const a = area.getBoundingClientRect()
    const e = el.getBoundingClientRect()
    const painel = { topo: a.top, base: a.bottom }
    const item = { topo: e.top, base: e.bottom }
    // Na transcrição a fala atual fica a um terço do topo; nas outras abas basta estar à vista.
    area.scrollTop += noTerco ? deltaParaUmTerco(painel, item) : deltaDeRolagem(painel, item)
  }

  // O painel acompanha o item atual, menos quando a pessoa acabou de rolar; passada a pausa, volta a ele.
  const chaveAtualRef = useRef(chaveAtual)
  const noTercoRef = useRef(aba === 'transcricao')
  useEffect(() => {
    chaveAtualRef.current = chaveAtual
    noTercoRef.current = aba === 'transcricao'
  }, [chaveAtual, aba])
  const fimDaPausa = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(fimDaPausa.current), [])
  function rolouAMao() {
    ultimaRolagem.current = Date.now()
    clearTimeout(fimDaPausa.current)
    fimDaPausa.current = setTimeout(() => {
      if (chaveAtualRef.current) mostrar(chaveAtualRef.current, noTercoRef.current)
    }, PAUSA_DA_ROLAGEM_MS)
  }
  useEffect(() => {
    if (!chaveAtual || Date.now() - ultimaRolagem.current < PAUSA_DA_ROLAGEM_MS) return
    mostrar(chaveAtual, aba === 'transcricao')
  }, [chaveAtual, aba])

  // A seleção só entra na vista; o terço é do acompanhamento da fala que toca.
  useEffect(() => {
    if (selecionada) mostrar(selecionada, false)
  }, [selecionada, aba])

  const indiceDaAba = ABAS.findIndex((a) => a.chave === aba)
  const trocar = (passo: -1 | 1) =>
    aoTrocarAba(ABAS[Math.min(Math.max(indiceDaAba + passo, 0), ABAS.length - 1)].chave)
  const mover = (passo: -1 | 1) => {
    const chave = vizinhoNoPainel(navegaveis.map((i) => i.chave), selecionada, passo)
    if (chave) aoSelecionar(chave)
  }

  useAtalhos([
    {
      tecla: '↑ ↓',
      acao: 'No painel: mover a seleção na aba',
      grupo: GRUPO,
      casa: (e) => e.key === 'ArrowUp' || e.key === 'ArrowDown',
      executar: (e) => mover(e.key === 'ArrowUp' ? -1 : 1),
    },
    {
      tecla: 'Enter',
      acao: 'No painel: saltar o player ao item selecionado',
      grupo: GRUPO,
      // Com o foco num botão ou link, o Enter faz o que o elemento faz; menos na aba e no próprio item,
      // em que o foco pode ter ficado num item enquanto as setas moveram a seleção.
      casa: (e) =>
        e.key === 'Enter' &&
        !(e.target instanceof HTMLElement && e.target.closest('button:not([role="tab"]):not([data-item]), a')),
      executar: () => {
        if (selecionado) aoSaltar(selecionado.inicio_ms)
      },
    },
    {
      tecla: 'Ctrl + ← →',
      acao: 'No painel: trocar de aba',
      grupo: GRUPO,
      ctrl: true,
      casa: (e) => e.key === 'ArrowLeft' || e.key === 'ArrowRight',
      executar: (e) => trocar(e.key === 'ArrowLeft' ? -1 : 1),
    },
  ])

  const lista = (itensDaLista: ItemDoPainel[]) =>
    itensDaLista.map((i) => (
      <Item
        key={i.chave}
        item={i}
        atual={contem(i, atualMs)}
        selecionado={i.chave === selecionada}
        aoClicar={(x) => {
          aoSelecionar(x.chave)
          aoSaltar(x.inicio_ms)
        }}
        aoSaltar={aoSaltar}
        aoReproduzir={aoReproduzir}
      />
    ))

  let conteudo: ReactNode
  if (aba === 'agora') {
    const agoraItens = agora(itens, atualMs)
    conteudo =
      agoraItens.length === 0 ? (
        <Text size="sm" c="dimmed">
          Nada decupado neste momento.
        </Text>
      ) : (
        TIPOS_DO_AGORA.map((t) => {
          const doTipo = agoraItens.filter((i) => i.tipo === t)
          return doTipo.length > 0 && (
            <Secao key={t} titulo={TITULO_DO_TIPO[t]}>
              {lista(doTipo)}
            </Secao>
          )
        })
      )
  } else if (aba === 'pessoas') {
    conteudo =
      pessoas.length === 0 && mencoes.length === 0 ? (
        <Text size="sm" c="dimmed">
          {VAZIO_DA_ABA.pessoas}
        </Text>
      ) : (
        <>
          {pessoas.length > 0 && (
            <Secao titulo="Pessoas na imagem">
              {pessoas.map((p) => {
                const doId = aparicoes.filter((i) => i.pessoa === p.id)
                const abrir = pessoasAbertas.has(p.id)
                const rotulo = doId[0]?.titulo ?? p.nome
                return (
                  <Stack key={p.id} gap={2}>
                    <UnstyledButton
                      aria-expanded={abrir}
                      aria-label={`${rotulo}, ${doId.length} ${doId.length === 1 ? 'aparição' : 'aparições'}`}
                      onClick={() => aoAbrirPessoa(p.id)}
                      p="xs"
                    >
                      <Group gap="xs" justify="space-between" wrap="nowrap">
                        <Stack gap={0}>
                          <Text size="sm">{rotulo}</Text>
                          {doId[0]?.linhas[0] && rotulo === NAO_IDENTIFICADO && (
                            <Text size="xs" c="dimmed">{doId[0].linhas[0]}</Text>
                          )}
                        </Stack>
                        <Group gap="xs" wrap="nowrap">
                          {(doId[0]?.selos ?? []).map((s) => (
                            <Badge key={s.rotulo} size="sm">{s.rotulo}</Badge>
                          ))}
                          <Text size="xs" c="dimmed">{`${doId.length} ${doId.length === 1 ? 'aparição' : 'aparições'}`}</Text>
                        </Group>
                      </Group>
                    </UnstyledButton>
                    {abrir && <Stack gap={2} ml="md">{lista(doId)}</Stack>}
                  </Stack>
                )
              })}
            </Secao>
          )}
          {mencoes.length > 0 && (
            <Secao titulo="Só citadas (não contam como tempo de tela)">{lista(mencoes)}</Secao>
          )}
        </>
      )
  } else {
    const doTipo = itensDaAba(itens, aba)
    conteudo =
      doTipo.length === 0 ? (
        <Text size="sm" c="dimmed">
          {VAZIO_DA_ABA[aba]}
        </Text>
      ) : (
        lista(doTipo)
      )
  }

  return (
    <Stack gap="sm" style={{ height: '100%', minHeight: 0 }}>
      <Cabecalho itens={itens} pautas={pautas} duracaoMs={duracaoMs} atualMs={atualMs} />
      <Group gap="xs" role="tablist" aria-label="Abas do painel" wrap="wrap">
        {ABAS.map((a) => {
          const ativa = a.chave === aba
          const n = a.chave === 'agora' ? null : contagens[a.chave]
          return (
            <UnstyledButton
              key={a.chave}
              role="tab"
              aria-selected={ativa}
              tabIndex={ativa ? 0 : -1}
              onClick={() => aoTrocarAba(a.chave)}
              px="xs"
              py={2}
              style={{
                borderRadius: 'var(--mantine-radius-sm)',
                background: ativa ? SELECIONADO.background : undefined,
                fontSize: 'var(--mantine-font-size-sm)',
                fontWeight: ativa ? 600 : undefined,
              }}
            >
              {a.rotulo}
              {n !== null && (
                <>
                  {' '}
                  <Text span size="xs" c="dimmed">
                    {n}
                  </Text>
                </>
              )}
            </UnstyledButton>
          )
        })}
      </Group>
      <Stack
        ref={rolagem}
        role="tabpanel"
        gap="sm"
        onWheel={rolouAMao}
        onTouchMove={rolouAMao}
        onPointerDown={rolouAMao}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', position: 'relative' }}
      >
        {conteudo}
      </Stack>
    </Stack>
  )
}
