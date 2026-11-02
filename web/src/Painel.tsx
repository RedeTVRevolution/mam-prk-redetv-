import { ActionIcon, Badge, Box, Group, Stack, Text, Tooltip, UnstyledButton, Button } from '@mantine/core'
import { IconPencil, IconTrash } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { FotosDoNome } from './api.ts'
import { useAtalhos } from './atalhos.ts'
import { ComparacaoDoRosto } from './ComparacaoDoRosto.tsx'
import { InventarioDoPlano, type ObjetoApontado } from './Inventario.tsx'
import { type Marca, ROTULO_NA_BUSCA } from './catalogacao.ts'
import { MiniaturaDoPainel } from './Miniatura.tsx'
import { type Intervalo, relogio, SEM_OBJETOS } from './linhaDoTempo.ts'
import {
  ABAS,
  type Aba,
  agora,
  contem,
  deltaDeRolagem,
  deltaParaUmTerco,
  type DadosDoObjeto,
  type ItemDoPainel,
  itensDaAba,
  itensDoPainel,
  NAO_IDENTIFICADO,
  objetosDaAba,
  semDecupagemEm,
  type Selo,
  textoDoSemDecupagem,
  TIPOS_DO_AGORA,
  type TipoDoItem,
  vizinhoNoPainel,
} from './painel.ts'
import { CORES, CORES_DE_OBJETO, CORES_DE_OCORRENCIA } from './tema.ts'
import type { Decupagem } from './decupagem.ts'

/** Depois que a pessoa rola o painel, ele não anda sozinho por este tempo. */
const PAUSA_DA_ROLAGEM_MS = 5000

const GRUPO = 'Painel'

/** O que toma o lugar da linha de um item (ou, com `acrescentar:<pessoa>`, abre sob a linha da pessoa). */
export interface EdicaoNoPainel {
  chave: string
  conteudo: ReactNode
}

const COR_DO_TIPO: Record<TipoDoItem, string> = {
  pauta: CORES_DE_OCORRENCIA.pauta.cor,
  aparicao: CORES_DE_OCORRENCIA.aparicao.cor,
  mencao: CORES_DE_OCORRENCIA.mencao.cor,
  objeto: CORES_DE_OCORRENCIA.objeto.cor,
  comercial: CORES_DE_OCORRENCIA.comercial.cor,
  texto: CORES_DE_OCORRENCIA.texto_na_tela.cor,
  plano: CORES.textoSecundario,
  fala: CORES_DE_OCORRENCIA.fala.cor,
}

const TITULO_DO_TIPO: Partial<Record<TipoDoItem, string>> = {
  aparicao: 'Pessoas na imagem',
  mencao: 'Menções',
  objeto: 'Objetos',
  comercial: 'Comerciais',
  texto: 'Textos na tela',
}

const VAZIO_DA_ABA: Record<Exclude<Aba, 'agora'>, string> = {
  pessoas: 'Nenhuma pessoa neste vídeo.',
  pautas: 'Nenhuma pauta neste vídeo.',
  objetos: SEM_OBJETOS,
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

/** O que o clique no selo "Rosto" precisa para abrir a comparação. */
interface Comparacao {
  pessoa: string
  nome: string
  quadro: string | null
}

function SeloDaProva({
  selo,
  aoSaltar,
  aoComparar,
}: {
  selo: Selo
  aoSaltar: (ms: number) => void
  /** Sem ele, o selo "Rosto" é só texto. */
  aoComparar?: () => void
}) {
  if (selo.tipo === 'nao_confirmado') {
    return (
      <Tooltip label={selo.dica} multiline w={260} events={{ hover: true, focus: true, touch: true }}>
        <Badge size="sm" variant="outline" color={CORES.textoSecundario} tabIndex={0}>
          {selo.rotulo}
        </Badge>
      </Tooltip>
    )
  }
  if (selo.tipo === 'rosto' && aoComparar) {
    return (
      <Badge
        size="sm"
        component="button"
        type="button"
        style={{ cursor: 'pointer' }}
        aria-label="Rosto: ver a comparação com as fotos de referência"
        onClick={aoComparar}
      >
        {selo.rotulo}
      </Badge>
    )
  }
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

/** O quadradinho da cor base (10 px) e o tom em palavras: a cor nunca vem sem a palavra. */
function CorDoObjeto({ dados }: { dados: DadosDoObjeto }) {
  return (
    <Group gap={6} wrap="nowrap" align="center">
      {dados.coresBase.slice(0, 2).map((c) => (
        <Box
          key={c}
          aria-hidden
          data-cor-base={c}
          style={{
            width: 10,
            height: 10,
            flex: 'none',
            background: CORES_DE_OBJETO[c],
            border: `1px solid ${CORES.textoSecundario}`,
            borderRadius: 'var(--mantine-radius-xs)',
          }}
        />
      ))}
      {dados.tom && <Text size="xs">{dados.tom}</Text>}
    </Group>
  )
}

/** Cor, categoria, marca, detalhe e dono do objeto; o dono na imagem é um botão que leva à aba Pessoas. */
function DescricaoDoObjeto({
  dados,
  aoIrParaDono,
}: {
  dados: DadosDoObjeto
  aoIrParaDono: (pessoa: string) => void
}) {
  const { dono } = dados
  const nomeDoDono = dono?.naImagem ? (
    <UnstyledButton
      component="button"
      type="button"
      onClick={() => aoIrParaDono(dono.id)}
      style={{ fontSize: 'inherit', color: CORES.focoTexto, textDecoration: 'underline' }}
    >
      {dono.nome}
    </UnstyledButton>
  ) : (
    dono?.nome
  )
  return (
    <Stack gap={0} ml={16}>
      <CorDoObjeto dados={dados} />
      {/* Sem dono, a linha do dono já diz "em cena"; a categoria em cena não se repete. */}
      {(dono || dados.categoria !== 'em cena') && (
        <Text size="xs" c="dimmed">
          {dados.categoria}
        </Text>
      )}
      <Text size="xs">
        {!dono ? (
          'em cena'
        ) : dono.relacao ? (
          <>
            {nomeDoDono} {dono.relacao}
          </>
        ) : (
          <>de {nomeDoDono}</>
        )}
      </Text>
      {dados.marca && <Text size="xs">{`marca ${dados.marca}`}</Text>}
      {dados.detalhe && (
        <Text size="xs" c="dimmed">
          {dados.detalhe}
        </Text>
      )}
    </Stack>
  )
}

function Item({
  item,
  atual,
  selecionado,
  aoClicar,
  aoSaltar,
  aoReproduzir,
  aoIrParaDono,
  aoComparar,
  urlDoQuadro,
  aoApontarObjeto,
  compacto,
  edicao,
  marca,
  acoes,
}: {
  item: ItemDoPainel
  atual: boolean
  selecionado: boolean
  aoClicar: (i: ItemDoPainel) => void
  aoSaltar: (ms: number) => void
  aoReproduzir: (i: ItemDoPainel) => void
  aoIrParaDono: (pessoa: string) => void
  /** Abre a comparação do rosto da pessoa do item; sem ele, o selo "Rosto" é só texto. */
  aoComparar?: (c: Comparacao) => void
  urlDoQuadro?: (caminho: string) => Promise<string>
  /** O objeto do inventário sob o mouse ou o foco; `null` quando sai. */
  aoApontarObjeto?: (o: ObjetoApontado | null) => void
  /** Objeto na lista das ocorrências: só o tipo e o tempo, o resto fica na linha do objeto. */
  compacto?: boolean
  /** O formulário (ou a confirmação) que substitui a linha enquanto o item é corrigido. */
  edicao?: ReactNode
  marca?: Marca
  /** Só no modo de catalogação: o lápis, a lixeira e o duplo clique, com o mouse no lugar do F2 e do Del. */
  acoes?: AcoesDaLinha
}) {
  const [sobre, setSobre] = useState(false)
  const [comFoco, setComFoco] = useState(false)
  const resumo = item.tipo === 'pauta' && item.detalhe
  return (
    <Box
      data-chave={item.chave}
      aria-current={atual ? 'true' : undefined}
      p="xs"
      onMouseOver={() => setSobre(true)}
      onMouseOut={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setSobre(false)
      }}
      onFocus={() => setComFoco(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setComFoco(false)
      }}
      style={{ position: 'relative', borderRadius: 'var(--mantine-radius-sm)', ...(atual ? ATUAL : {}), ...(selecionado ? { background: SELECIONADO.background } : {}) }}
    >
      {edicao ? (
        edicao
      ) : (
        <>
          <UnstyledButton
            data-item
            aria-label={
              item.tipo === 'fala'
                ? `${item.linhas[0] ? `${item.linhas[0]}: ` : ''}${item.titulo}, ${relogio(item.inicio_ms)}`
                : `${item.titulo}, ${relogio(item.inicio_ms)} a ${relogio(item.fim_ms)}`
            }
            aria-pressed={selecionado}
            onClick={() => aoClicar(item)}
            onDoubleClick={acoes?.podeCorrigir(item) ? () => acoes.corrigir(item) : undefined}
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
                {item.quadro !== undefined && !compacto && (
                  <MiniaturaDoPainel caminho={item.quadro} urlDoQuadro={urlDoQuadro} />
                )}
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
          {item.objeto && !compacto && <DescricaoDoObjeto dados={item.objeto} aoIrParaDono={aoIrParaDono} />}
          {item.inventario && !compacto && (
            <InventarioDoPlano inventario={item.inventario} plano={item.titulo} aoApontar={aoApontarObjeto ?? (() => {})} />
          )}
          {(item.selos.length > 0 || selecionado || marca) && (
            <Group gap="xs" mt={4} ml={16}>
              {item.selos.map((s) => (
                <SeloDaProva
                  key={s.rotulo}
                  selo={s}
                  aoSaltar={aoSaltar}
                  aoComparar={
                    aoComparar && item.pessoa
                      ? () => aoComparar({ pessoa: item.pessoa!, nome: item.titulo, quadro: item.quadro ?? null })
                      : undefined
                  }
                />
              ))}
              {marca && (
                <Tooltip label={marca.dica}>
                  <Badge size="sm" variant="light" color={marca.pendente || marca.na_busca === 'indexando' ? CORES.andamento : CORES.concluido} tabIndex={0}>
                    {marca.pendente ? 'aguardando o Curador' : ROTULO_NA_BUSCA[marca.na_busca]}
                  </Badge>
                </Tooltip>
              )}
              {selecionado && (
                <Button size="compact-xs" variant="default" onClick={() => aoReproduzir(item)}>
                  Reproduzir trecho
                </Button>
              )}
            </Group>
          )}
        </>
      )}
      {acoes && !edicao && (
        // Sempre no DOM (e na ordem do Tab): só ficam à vista com o mouse, o foco ou o item selecionado.
        <Group
          gap={2}
          wrap="nowrap"
          style={{ position: 'absolute', top: 4, right: 4, opacity: sobre || comFoco || selecionado ? 1 : 0 }}
        >
          {acoes.podeCorrigir(item) && (
            <Tooltip label="Corrigir (F2)">
              <ActionIcon size="sm" variant="subtle" aria-label={`Corrigir ${item.titulo}`} onClick={() => acoes.corrigir(item)}>
                <IconPencil size={14} />
              </ActionIcon>
            </Tooltip>
          )}
          {acoes.podeRemover(item) && (
            <Tooltip label="Não é isto (Del)">
              <ActionIcon size="sm" variant="subtle" aria-label={`Não é isto: ${item.titulo}`} onClick={() => acoes.remover(item)}>
                <IconTrash size={14} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      )}
    </Box>
  )
}

/** O que o mouse faz na linha do item, no modo de catalogação. */
export interface AcoesDaLinha {
  corrigir: (i: ItemDoPainel) => void
  remover: (i: ItemDoPainel) => void
  podeCorrigir: (i: ItemDoPainel) => boolean
  podeRemover: (i: ItemDoPainel) => boolean
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
  urlDoQuadro,
  aoApontarObjeto,
  atalhosAtivos = true,
  fotosDoNome,
  edicao = null,
  marcas,
  aoAcrescentar,
  acoes,
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
  /** A URL assinada do quadro de um momento; sem ela as miniaturas ficam como retângulo. */
  urlDoQuadro?: (caminho: string) => Promise<string>
  /** O objeto do inventário sob o mouse ou o foco, para o player mostrar o quadro com a caixa. */
  aoApontarObjeto?: (o: ObjetoApontado | null) => void
  /** Falso com a gaveta aberta: as setas e o Enter são dela. */
  atalhosAtivos?: boolean
  /** As fotos de referência do nome de uma pessoa; sem ele, o selo "Rosto" não abre a comparação. */
  fotosDoNome?: (pessoaId: string) => Promise<FotosDoNome>
  /** A correção em curso: o formulário toma o lugar da linha do item. */
  edicao?: EdicaoNoPainel | null
  /** "corrigido" e "aguardando o Curador", por chave de item. */
  marcas?: Record<string, Marca>
  /** Só no modo de catalogação: acrescentar uma aparição na linha da pessoa. */
  aoAcrescentar?: (pessoa: string) => void
  /** Só no modo de catalogação: corrigir e remover pelo mouse. */
  acoes?: AcoesDaLinha
}) {
  const [comparando, setComparando] = useState<Comparacao | null>(null)
  const fecharComparacao = useCallback(() => setComparando(null), [])
  const carregarFotos = useCallback(
    () => (comparando && fotosDoNome ? fotosDoNome(comparando.pessoa) : Promise.reject(new Error('sem rota'))),
    [comparando, fotosDoNome],
  )
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

  // Os objetos com a lista de ocorrências aberta; o objeto da ocorrência selecionada abre sozinho.
  const [objetosAbertos, setObjetosAbertos] = useState<ReadonlySet<string>>(new Set())
  const alternarObjeto = useCallback(
    (id: string) =>
      setObjetosAbertos((a) => {
        const novo = new Set(a)
        if (!novo.delete(id)) novo.add(id)
        return novo
      }),
    [],
  )
  const objetoSelecionado = selecionado?.objeto?.id
  // Ajuste durante a renderização: só quando o objeto selecionado muda, e depois fecha no clique.
  const [objetoVisto, setObjetoVisto] = useState<string | undefined>(undefined)
  if (objetoSelecionado !== objetoVisto) {
    setObjetoVisto(objetoSelecionado)
    if (objetoSelecionado && !objetosAbertos.has(objetoSelecionado)) {
      setObjetosAbertos(new Set(objetosAbertos).add(objetoSelecionado))
    }
  }

  const objetos = useMemo(() => objetosDaAba(itens), [itens])

  const { aparicoes, mencoes } = useMemo(() => {
    const daAba = itensDaAba(itens, 'pessoas')
    return { aparicoes: daAba.filter((i) => i.tipo === 'aparicao'), mencoes: daAba.filter((i) => i.tipo === 'mencao') }
  }, [itens])
  const pessoas = useMemo(() => decupagem.pessoas.filter((p) => p.na_imagem.length > 0), [decupagem])

  const contagens: Record<Exclude<Aba, 'agora'>, number> = {
    pessoas: pessoas.length,
    pautas: pautas.length,
    objetos: objetos.length,
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
    if (aba === 'objetos') return objetos.filter((o) => objetosAbertos.has(o.dados.id)).flatMap((o) => o.ocorrencias)
    return itensDaAba(itens, aba)
  }, [aba, itens, atualMs, pessoasAbertas, pessoas, aparicoes, mencoes, objetos, objetosAbertos])

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
      casa: (e) => atalhosAtivos && (e.key === 'ArrowUp' || e.key === 'ArrowDown'),
      executar: (e) => mover(e.key === 'ArrowUp' ? -1 : 1),
    },
    {
      tecla: 'Enter',
      acao: 'No painel: saltar o player ao item selecionado',
      grupo: GRUPO,
      // Com o foco num botão ou link, o Enter faz o que o elemento faz; menos na aba e no próprio item,
      // em que o foco pode ter ficado num item enquanto as setas moveram a seleção.
      casa: (e) =>
        atalhosAtivos &&
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
      casa: (e) => atalhosAtivos && (e.key === 'ArrowLeft' || e.key === 'ArrowRight'),
      executar: (e) => trocar(e.key === 'ArrowLeft' ? -1 : 1),
    },
  ])

  // O dono do objeto: abre a aba Pessoas na primeira aparição dele (a seleção abre a lista da pessoa).
  const irParaDono = (pessoa: string) => {
    aoTrocarAba('pessoas')
    const primeira = itens.find((i) => i.tipo === 'aparicao' && i.pessoa === pessoa)
    if (primeira) aoSelecionar(primeira.chave)
  }

  const lista = (itensDaLista: ItemDoPainel[], compacto?: boolean) =>
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
        aoIrParaDono={irParaDono}
        aoComparar={fotosDoNome ? setComparando : undefined}
        urlDoQuadro={urlDoQuadro}
        aoApontarObjeto={aoApontarObjeto}
        compacto={compacto}
        edicao={edicao?.chave === i.chave ? edicao.conteudo : undefined}
        marca={marcas?.[i.chave]}
        acoes={acoes}
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
                    <Group gap="xs" justify="space-between" wrap="nowrap" align="flex-start">
                      <UnstyledButton
                        aria-expanded={abrir}
                        aria-label={`${rotulo}, ${doId.length} ${doId.length === 1 ? 'aparição' : 'aparições'}`}
                        onClick={() => aoAbrirPessoa(p.id)}
                        p="xs"
                        style={{ flex: 1, minWidth: 0, textAlign: 'left' }}
                      >
                        <Group gap="xs" justify="space-between" wrap="nowrap">
                          <Stack gap={0}>
                            <Text size="sm">{rotulo}</Text>
                            {doId[0]?.linhas[0] && rotulo === NAO_IDENTIFICADO && (
                              <Text size="xs" c="dimmed">{doId[0].linhas[0]}</Text>
                            )}
                          </Stack>
                          <Text size="xs" c="dimmed">{`${doId.length} ${doId.length === 1 ? 'aparição' : 'aparições'}`}</Text>
                        </Group>
                      </UnstyledButton>
                      <Group gap="xs" wrap="wrap" p="xs" justify="flex-end">
                        {(doId[0]?.selos ?? []).map((s) => (
                          <SeloDaProva
                            key={s.rotulo}
                            selo={s}
                            aoSaltar={aoSaltar}
                            aoComparar={
                              fotosDoNome
                                ? () => setComparando({ pessoa: p.id, nome: rotulo, quadro: doId[0]?.quadro ?? null })
                                : undefined
                            }
                          />
                        ))}
                      </Group>
                    </Group>
                    {abrir && aoAcrescentar && edicao?.chave !== `acrescentar:${p.id}` && (
                      <Button size="compact-xs" variant="default" ml="md" style={{ alignSelf: 'flex-start' }} onClick={() => aoAcrescentar(p.id)}>
                        {`Acrescentar aparição de ${rotulo}`}
                      </Button>
                    )}
                    {edicao?.chave === `acrescentar:${p.id}` && <Box ml="md">{edicao.conteudo}</Box>}
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
  } else if (aba === 'objetos') {
    conteudo =
      objetos.length === 0 ? (
        <Text size="sm" c="dimmed">
          {VAZIO_DA_ABA.objetos}
        </Text>
      ) : (
        objetos.map(({ dados, ocorrencias }) => {
          const abrir = objetosAbertos.has(dados.id)
          const quantas = `${ocorrencias.length} ${ocorrencias.length === 1 ? 'ocorrência' : 'ocorrências'}`
          return (
            <Stack key={dados.id} gap={2}>
              <UnstyledButton
                aria-expanded={abrir}
                aria-label={`${dados.tipo}, ${quantas}`}
                onClick={() => alternarObjeto(dados.id)}
                p="xs"
              >
                <Group gap="xs" justify="space-between" wrap="nowrap">
                  <MiniaturaDoPainel caminho={ocorrencias[0]?.quadro ?? null} urlDoQuadro={urlDoQuadro} />
                  <Text size="sm" style={{ flex: 1 }}>
                    {dados.tipo}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {quantas}
                  </Text>
                </Group>
              </UnstyledButton>
              <Box px="xs">
                <DescricaoDoObjeto dados={dados} aoIrParaDono={irParaDono} />
              </Box>
              {abrir && (
                <Stack gap={2} ml="md">
                  {lista(ocorrencias, true)}
                </Stack>
              )}
            </Stack>
          )
        })
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
    <Stack gap="sm" style={{ height: '100%', minHeight: 0, position: 'relative' }}>
      {comparando && (
        <ComparacaoDoRosto
          nome={comparando.nome}
          quadro={comparando.quadro}
          carregar={carregarFotos}
          urlDoQuadro={urlDoQuadro}
          aoFechar={fecharComparacao}
        />
      )}
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
