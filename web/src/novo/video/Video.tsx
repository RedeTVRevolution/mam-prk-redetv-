import {
  IconArrowBackUp,
  IconArrowForwardUp,
  IconDots,
  IconDownload,
  IconExternalLink,
  IconEye,
  IconFileDownload,
  IconLayoutSidebarRightExpand,
  IconLink,
  IconMaximize,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconVolume,
  IconVolumeOff,
} from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { codigoDoErro, ConflitoNaApi, PedidoInvalido, SessaoExpirada } from '../../api.ts'
import { useAtalhos } from '../../atalhos.ts'
import { filtrosDeQuemAcessou } from '../../auditoria.ts'
import { baixarDecupagem, baixarPelaUrl } from '../../baixar.ts'
import {
  aindaIndexando,
  editorDeNovaAparicao,
  editorDoItem,
  marcasDosItens,
  motivoDaRemocao,
  type Pedido,
  pedidoDeRemocao,
  podeRemover,
} from '../../catalogacao.ts'
import type { Pauta, Sugestao } from '../../decupagem.ts'
import { cabeNaPauta, editorDeDivisao, editorDeJuncao, pautasParaJuntar } from '../../pautas.ts'
import { nomeDaEtapa } from '../../etapas.ts'
import { naInterfaceAtual } from '../../interface.ts'
import { dataDeExibicao, finalizando, type Job } from '../../jobs.ts'
import { type Borda, duracaoDaLinha, faixasDoVisualizador, type Intervalo, relogio } from '../../linhaDoTempo.ts'
import { ESTADOS_QUE_VAO_PARA_A_LIXEIRA } from '../../lixeira.ts'
import { NomesDoCatalogo } from '../../nomesDoCatalogo.ts'
import { type ItemDoPainel, itensDoPainel, nomeNormalizado } from '../../painel.ts'
import { criarCacheDeQuadros } from '../../quadros.ts'
import { ACERVO, enderecoDaAuditoria, enderecoDoVideo, navegar, seguir } from '../../rotas.ts'
import { timecodeNoInstante } from '../../timecode.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Kbd } from '../ui/kbd.tsx'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '../ui/dropdown-menu.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { AvisoDeFalha, BotaoComDica, BotaoDeIcone } from './comum.tsx'
import { ComparacaoDePassada, SeletorDePassada } from './Comparacao.tsx'
import type { ResumoDaPassada } from '../../passadas.ts'
import { Sugestoes } from './Sugestoes.tsx'
import { type Revisao, useRevisao } from './useRevisao.ts'
import { chaveDoVideo, FAIXAS_DE_INICIO, SECAO_DO_TIPO, type Secao, tipoDaChave } from './tipos.ts'
import { ConfirmacaoDeRemocao, FormularioDeCorrecao } from './Correcao.tsx'
import { FusaoDePessoa } from './FusaoDePessoa.tsx'
import { RenomeacaoEmLote } from './RenomeacaoEmLote.tsx'
import { type DialogoDoVideo, DialogosDoVideo } from './dialogos.tsx'
import { criarInstante, type Instante, useNoInstante } from './instante.ts'
import { type AcoesDeCorrecao, Inspetor } from './Inspetor.tsx'
import { ChipsDasFaixas, type AlcasDaCorrecao, LinhaDoTempo } from './LinhaDoTempo.tsx'

export interface Permissoes {
  editar: boolean
  reprocessar: boolean
  verAuditoria: boolean
  apagar: boolean
  /** `correcao.aprovar`: o Curador (renomear em todos os vídeos). */
  aprovar: boolean
  /** `catalogo.fundir`. */
  fundir: boolean
}

const VELOCIDADES = [1, 2, 4]
const SALTO_CURTO_S = 1
const SALTO_LONGO_S = 5
const AVISO_CURTO_MS = 1500
const AVISO_MS = 5000

const GRUPO = 'Player'
const GRUPO_DA_LINHA = 'Linha do tempo'
const GRUPO_DO_INSPETOR = 'Inspetor'
const GRUPO_DA_CORRECAO = 'Correção'
const GRUPO_DA_CATALOGACAO = 'Catalogação'

/** O evento é de uma destas teclas (letras sem diferença de caixa). */
const tecla = (e: KeyboardEvent, ...teclas: string[]): boolean => teclas.includes(e.key.toLowerCase())

function tocar(player: HTMLVideoElement) {
  // O navegador recusa o play sem gesto ou com o arquivo ainda sem carregar: sem erro na tela.
  Promise.resolve(player.play()).catch(() => {})
}

type Edicao = { chave: string; modo: 'editar' | 'remover' | 'acrescentar' | 'fundir' | 'renomear' }

/**
 * O vídeo aberto: o `<video>` com o proxy assinado, as barras, a linha do tempo e o inspetor. O
 * instante do vídeo fica fora do estado desta tela (`instante.ts`): tocar não a renderiza de novo.
 */
export function Video({
  job,
  t,
  pode,
  reprocessou,
  aoReprocessar,
  intervaloDaIndexacaoMs,
}: {
  job: Job
  t: number | null
  pode: Permissoes
  reprocessou: boolean
  aoReprocessar: (job: Job, etapa: string) => void
  intervaloDaIndexacaoMs: number
}) {
  const api = useApi()
  const consultas = useQueryClient()
  const cliente = useMemo(() => api.job(job.id), [api, job.id])
  const concluido = job.estado === 'concluido'
  const [instante] = useState(criarInstante)
  const player = useRef<HTMLVideoElement>(null)
  const moldura = useRef<HTMLDivElement>(null)
  const retomarEm = useRef<number | null>(t)
  // "Tocar o trecho": onde o player para sozinho.
  const pararEm = useRef<number | null>(null)
  const [duracaoMs, setDuracaoMs] = useState((job.duracao_s ?? 0) * 1000)
  const [tocando, setTocando] = useState(false)
  const [velocidade, setVelocidade] = useState(1)
  const [falhaDaMidia, setFalhaDaMidia] = useState<string | null>(null)
  const [dialogo, setDialogo] = useState<DialogoDoVideo | null>(null)
  const [comparandoCom, setComparandoCom] = useState<string | null>(null)
  // Juntar e dividir pautas: os ids marcados e o formulário aberto.
  const [pautasMarcadas, setPautasMarcadas] = useState<ReadonlySet<string>>(new Set())
  const [estrutura, setEstrutura] = useState<{ modo: 'juntar'; pautas: Pauta[] } | { modo: 'dividir'; pauta: Pauta; em_ms: number } | null>(null)

  const reproducao = useQuery({
    queryKey: chaveDoVideo(job.id, 'reproducao'),
    queryFn: () => cliente.reproducao(),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  })
  const decupagem = useQuery({
    queryKey: chaveDoVideo(job.id, 'decupagem'),
    queryFn: () => cliente.decupagem(),
    enabled: concluido,
    retry: false,
    staleTime: Infinity,
  })
  // O catálogo de correções (rótulos e vocabulários) e o histórico só servem a quem edita.
  const catalogo = useQuery({
    queryKey: chaveDoVideo(job.id, 'catalogo'),
    queryFn: () => cliente.catalogo(),
    enabled: pode.editar,
    retry: false,
    staleTime: Infinity,
  })
  const d = decupagem.data
  // As passadas de comparação: lista vazia quando não há, ou quando a pessoa não pode vê-las.
  const passadas = useQuery({
    queryKey: chaveDoVideo(job.id, 'passadas'),
    queryFn: () => cliente.passadas(),
    enabled: concluido,
    retry: false,
    staleTime: Infinity,
  })
  // Uma correção nova entra no índice depois de gravada: pergunta de novo até ela confirmar.
  const historico = useQuery({
    queryKey: chaveDoVideo(job.id, 'historico'),
    queryFn: () => cliente.historico(),
    enabled: pode.editar && !!d,
    retry: false,
    staleTime: Infinity,
    refetchInterval: (q) => (q.state.data && aindaIndexando(q.state.data) ? intervaloDaIndexacaoMs : false),
  })

  const itens = useMemo(() => (d ? itensDoPainel(d) : []), [d])
  const faixas = useMemo(() => (d ? faixasDoVisualizador(d) : null), [d])
  const duracaoDaLinhaMs = duracaoDaLinha(duracaoMs, faixas ?? [])
  const marcas = useMemo(
    () => (d && historico.data ? marcasDosItens(d, itens, historico.data) : undefined),
    [d, itens, historico.data],
  )
  // As URLs assinadas dos quadros valem alguns minutos: o cache evita pedir de novo a cada linha.
  const urlDoQuadro = useMemo(() => criarCacheDeQuadros((arquivo) => cliente.quadro(arquivo)), [cliente])

  const [selecionada, setSelecionada] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState(false)
  const [secao, setSecao] = useState<Secao | null>('pessoas')
  const [ligadas, setLigadas] = useState<ReadonlySet<string>>(() => new Set(FAIXAS_DE_INICIO))
  const [inspetorAberto, setInspetorAberto] = useState(true)
  const [edicao, setEdicao] = useState<Edicao | null>(null)
  // Os tempos que as alças da linha do tempo ajustaram na correção aberta.
  const [temposDaAlca, setTemposDaAlca] = useState<Intervalo | null>(null)
  const salvarDasAlcas = useRef<(() => void) | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const fimDoAviso = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(fimDoAviso.current), [])

  function mostrarAviso(texto: string) {
    setAviso(texto)
    clearTimeout(fimDoAviso.current)
    fimDoAviso.current = setTimeout(() => setAviso(null), AVISO_MS)
  }

  const revisao = useRevisao({
    id: job.id,
    pode: pode.editar,
    decupagemPronta: !!d,
    catalogo: catalogo.data,
    historico: historico.data,
    mostrarAviso,
    aoAlternar: () => {
      // Entrar ou sair do modo começa do zero: sem marcas nem formulário da revisão anterior.
      setPautasMarcadas(new Set())
      setEstrutura(null)
    },
  })

  // As sugestões do pipeline só aparecem na revisão; a lista vem de novo a cada entrada nela.
  const chaveDasSugestoes = chaveDoVideo(job.id, 'sugestoes')
  const sugestoes = useQuery({
    queryKey: chaveDasSugestoes,
    queryFn: () => cliente.sugestoes(),
    enabled: revisao.revisando && !!d,
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  })

  // Outro `?t=` no mesmo vídeo salta o player.
  const tAnterior = useRef(t)
  useEffect(() => {
    if (t === tAnterior.current) return
    tAnterior.current = t
    if (t === null) return
    pararEm.current = null
    if (player.current && player.current.readyState > 0) player.current.currentTime = t
    else retomarEm.current = t
  }, [t])

  /** O endereço copiado da barra é sempre o do momento atual, sem entrada nova no histórico. */
  function gravarNoEndereco() {
    if (!player.current) return
    const busca = new URLSearchParams(location.search).get('busca')
    history.replaceState(history.state, '', enderecoDoVideo(job.id, Math.floor(player.current.currentTime), busca))
  }

  function saltarPara(segundos: number) {
    const el = player.current
    if (!el) return
    pararEm.current = null
    const limite = Number.isFinite(el.duration) ? el.duration : Infinity
    el.currentTime = Math.min(Math.max(segundos, 0), limite)
    instante.definir(el.currentTime * 1000)
  }
  const saltarParaMs = (ms: number) => saltarPara(ms / 1000)

  function mudarVelocidade(v: number) {
    if (player.current) player.current.playbackRate = v
    setVelocidade(v)
  }

  function alternar() {
    const el = player.current
    if (!el) return
    pararEm.current = null
    if (el.paused) tocar(el)
    else el.pause()
  }

  function tocarMaisRapido() {
    const el = player.current
    if (!el) return
    // Pausado, o L recomeça o ciclo: toca em 1×.
    if (el.paused) {
      mudarVelocidade(1)
      tocar(el)
      return
    }
    mudarVelocidade(VELOCIDADES.find((v) => v > el.playbackRate) ?? VELOCIDADES[VELOCIDADES.length - 1])
  }

  function tocarTrecho(trecho: Intervalo) {
    const el = player.current
    if (!el) return
    saltarPara(trecho.inicio_ms / 1000)
    pararEm.current = trecho.fim_ms
    tocar(el)
  }

  function aoAtualizarOTempo(el: HTMLVideoElement) {
    // O `timeupdate` chega a cada ~250 ms: o player volta ao fim exato do trecho.
    if (pararEm.current !== null && el.currentTime * 1000 >= pararEm.current) {
      el.pause()
      el.currentTime = pararEm.current / 1000
      pararEm.current = null
    }
    instante.definir(el.currentTime * 1000)
  }

  const telaCheia = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void moldura.current?.requestFullscreen?.()
  }

  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e continua
  // do mesmo ponto. Com o link ainda válido, a falha é do arquivo, e pedir de novo não adianta.
  function aoFalharOPlayer() {
    const r = reproducao.data
    if (!r) return
    retomarEm.current = player.current?.currentTime ?? null
    if (Date.parse(r.expira_em) > Date.now()) setFalhaDaMidia(`midia_${player.current?.error?.code ?? 0}`)
    else void reproducao.refetch()
  }

  const fps = job.taxa_de_quadros ?? null
  const recuarOuAvancar = (passo: number) => ({
    casa: (e: KeyboardEvent) => (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.shiftKey === (passo === SALTO_LONGO_S),
    executar: (e: KeyboardEvent) => saltarPara((player.current?.currentTime ?? 0) + (e.key === 'ArrowLeft' ? -passo : passo)),
  })

  // ---------- seleção e correção ----------

  function fecharEdicao() {
    setEdicao(null)
    setTemposDaAlca(null)
  }

  function selecionar(chave: string | null) {
    if (chave !== selecionada) fecharEdicao()
    setSelecionada(chave)
  }

  /** Abre o item no inspetor (a seção do tipo e o detalhe); `saltar` leva o player ao início dele. */
  function abrirItem(chave: string, saltar: boolean) {
    selecionar(chave)
    setSecao(SECAO_DO_TIPO[tipoDaChave(chave)])
    setDetalhe(true)
    setInspetorAberto(true)
    const item = itens.find((i) => i.chave === chave)
    if (saltar && item) saltarParaMs(item.inicio_ms)
  }

  const catalogoPronto = pode.editar ? catalogo.data : undefined
  const selecionado = itens.find((i) => i.chave === selecionada)

  function corrigirItem(item: ItemDoPainel | undefined) {
    if (!d || !catalogoPronto) return
    if (!item || !editorDoItem(d, item, catalogoPronto)) {
      mostrarAviso('Selecione um item que possa ser corrigido (↑ ↓).')
      return
    }
    setEstrutura(null)
    abrirItem(item.chave, false)
    setTemposDaAlca(null)
    setEdicao({ chave: item.chave, modo: 'editar' })
  }

  function removerItem(item: ItemDoPainel | undefined) {
    if (!d || !catalogoPronto) return
    if (!item || !podeRemover(d, item)) {
      mostrarAviso('Não há "não é isto" para o item selecionado.')
      return
    }
    setEstrutura(null)
    abrirItem(item.chave, false)
    setTemposDaAlca(null)
    setEdicao({ chave: item.chave, modo: 'remover' })
  }

  // ---------- juntar e dividir pautas ----------

  // Depois de recarregar a decupagem, as marcas de pautas que sumiram não contam.
  const marcadasNaDecupagem = d?.pautas.filter((p) => pautasMarcadas.has(p.id)).length ?? 0

  function pautaDoItem(item: ItemDoPainel | undefined): Pauta | undefined {
    if (!d || item?.tipo !== 'pauta') return undefined
    return d.pautas[Number(item.chave.slice('pauta-'.length))]
  }

  function alternarMarcaDaPauta(item: ItemDoPainel | undefined) {
    const pauta = pautaDoItem(item)
    if (!pauta) {
      mostrarAviso('Selecione a pauta que vai ser marcada (↑ ↓).')
      return
    }
    setPautasMarcadas((marcadas) => {
      const novas = new Set(marcadas)
      if (!novas.delete(pauta.id)) novas.add(pauta.id)
      return novas
    })
  }

  function juntarMarcadas() {
    if (!d) return
    const r = pautasParaJuntar(d.pautas, pautasMarcadas)
    if ('aviso' in r) {
      mostrarAviso(r.aviso)
      return
    }
    fecharEdicao()
    setEstrutura({ modo: 'juntar', pautas: r.pautas })
  }

  function dividirPauta(item: ItemDoPainel | undefined) {
    const pauta = pautaDoItem(item)
    if (!pauta) {
      mostrarAviso('Selecione a pauta que vai ser dividida (↑ ↓).')
      return
    }
    const emMs = instante.ms()
    if (!cabeNaPauta(pauta, emMs)) {
      mostrarAviso('Leve o vídeo para dentro da pauta em foco para dividir (D).')
      return
    }
    fecharEdicao()
    setEstrutura({ modo: 'dividir', pauta, em_ms: emMs })
  }

  async function gravarEstrutura(pedidos: Pedido[], motivo: string): Promise<string | null> {
    const falha = await gravar(pedidos, motivo)
    if (!falha) {
      setPautasMarcadas(new Set())
      setEstrutura(null)
    }
    return falha
  }

  /** Uma correção, a fusão ou a renomeação mudaram a decupagem: busca de novo, com o histórico. */
  function recarregar() {
    void consultas.invalidateQueries({ queryKey: chaveDoVideo(job.id, 'decupagem') })
    void consultas.invalidateQueries({ queryKey: chaveDoVideo(job.id, 'historico') })
  }

  /** Grava os pedidos em sequência com o motivo; devolve o erro que fica no formulário, ou `null`. */
  async function gravar(pedidos: Pedido[], motivo: string): Promise<string | null> {
    if (!d) return null
    let gravadas = 0
    try {
      let versao = d.versao_decupagem
      for (const { pessoa_do_nome, ...p } of pedidos) {
        let item_id = p.item_id
        if (pessoa_do_nome) {
          // A pessoa acabou de ser acrescentada: o id dela está na decupagem recarregada.
          const atual = await cliente.decupagem()
          const alvo = nomeNormalizado(pessoa_do_nome)
          const pessoa = atual.pessoas.find((x) => nomeNormalizado(x.nome) === alvo)
          if (!pessoa) throw new PedidoInvalido('A pessoa acrescentada não apareceu na decupagem. Marque a menção pelo inspetor.')
          item_id = pessoa.id
          versao = atual.versao_decupagem
        }
        await cliente.corrigir({ ...p, item_id, motivo, versao })
        gravadas += 1
      }
    } catch (e) {
      if (e instanceof SessaoExpirada) return null
      const mensagem =
        e instanceof ConflitoNaApi || e instanceof PedidoInvalido ? e.message : 'Não foi possível gravar a correção. Tente de novo em instantes.'
      // Com a decupagem mudada (ou parte já gravada), a tela recarrega e o formulário fecha.
      if (e instanceof ConflitoNaApi || gravadas > 0) {
        recarregar()
        fecharEdicao()
        mostrarAviso(mensagem)
        return null
      }
      return mensagem
    }
    recarregar()
    fecharEdicao()
    return null
  }

  // O formulário (ou a confirmação) do item aberto no detalhe, e as alças dos tempos na linha do tempo.
  let conteudoDaEdicao: ReactNode = null
  let alcas: AlcasDaCorrecao | null = null
  if (d && catalogoPronto && edicao) {
    const item = itens.find((i) => i.chave === edicao.chave)
    if (edicao.modo === 'fundir') {
      const pessoa = d.pessoas.find((p) => `fundir:${p.id}` === edicao.chave)
      if (pessoa?.catalogo_id)
        conteudoDaEdicao = (
          <FusaoDePessoa
            origemId={pessoa.catalogo_id}
            nomeDaOrigem={pessoa.nome}
            fusao={api.fusao}
            limiteDoMotivo={catalogoPronto.limites.motivo}
            aoFundir={() => {
              fecharEdicao()
              recarregar()
            }}
            aoCancelar={fecharEdicao}
          />
        )
    } else if (edicao.modo === 'renomear') {
      const pessoa = d.pessoas.find((p) => `renomear:${p.id}` === edicao.chave)
      if (pessoa?.catalogo_id)
        conteudoDaEdicao = (
          <RenomeacaoEmLote pessoaId={pessoa.catalogo_id} nomeAtual={pessoa.nome} renomeacao={api.renomeacao} aoRenomear={recarregar} aoFechar={fecharEdicao} />
        )
    } else if (edicao.modo === 'acrescentar') {
      const pessoa = d.pessoas.find((p) => `acrescentar:${p.id}` === edicao.chave)
      if (pessoa)
        conteudoDaEdicao = (
          <FormularioDeCorrecao
            editor={editorDeNovaAparicao(pessoa, instante.ms(), catalogoPronto)}
            rotulo={`Acrescentar aparição de ${pessoa.nome}`}
            limiteDoMotivo={catalogoPronto.limites.motivo}
            aoSalvar={gravar}
            aoCancelar={fecharEdicao}
          />
        )
    } else if (item && edicao.modo === 'editar') {
      const editor = editorDoItem(d, item, catalogoPronto)
      if (editor) {
        conteudoDaEdicao = (
          <FormularioDeCorrecao
            editor={editor}
            rotulo={`Corrigir ${item.titulo}`}
            limiteDoMotivo={catalogoPronto.limites.motivo}
            tempos={temposDaAlca}
            salvarRef={salvarDasAlcas}
            aoSalvar={gravar}
            aoCancelar={fecharEdicao}
          />
        )
        if (editor.intervalo) {
          const atual = temposDaAlca ?? editor.intervalo
          alcas = {
            chave: item.chave,
            inicio_ms: atual.inicio_ms,
            fim_ms: atual.fim_ms,
            aoSalvar: () => salvarDasAlcas.current?.(),
            aoDescartar: fecharEdicao,
            aoMover: (borda: Borda, ms: number) => setTemposDaAlca({ ...atual, [borda === 'inicio' ? 'inicio_ms' : 'fim_ms']: ms }),
          }
        }
      }
    } else if (item && edicao.modo === 'remover') {
      const pedido = pedidoDeRemocao(d, item)
      if (pedido) {
        const alvo = item.tipo === 'mencao' ? 'desta menção' : 'desta aparição'
        conteudoDaEdicao = (
          <ConfirmacaoDeRemocao
            texto={item.tipo === 'objeto' ? 'Este objeto não está na imagem?' : `Remover ${item.titulo} ${alvo}?`}
            aoConfirmar={async () => {
              const falha = await gravar([pedido], motivoDaRemocao(pedido))
              if (falha) mostrarAviso(falha)
            }}
            aoCancelar={fecharEdicao}
          />
        )
      }
    }
  }

  const abrirPessoa = (modo: 'fundir' | 'renomear') => (pessoa: string) => {
    setTemposDaAlca(null)
    setEdicao({ chave: `${modo}:${pessoa}`, modo })
  }
  const acoes: AcoesDeCorrecao | undefined =
    d && catalogoPronto
      ? {
          podeCorrigir: (i) => !!editorDoItem(d, i, catalogoPronto),
          podeRemover: (i) => podeRemover(d, i),
          corrigir: corrigirItem,
          remover: removerItem,
          acrescentar: (pessoa) => {
            setTemposDaAlca(null)
            setEdicao({ chave: `acrescentar:${pessoa}`, modo: 'acrescentar' })
          },
          pautas: revisao.revisando
            ? {
                marcada: (i) => {
                  const p = pautaDoItem(i)
                  return !!p && pautasMarcadas.has(p.id)
                },
                alternar: alternarMarcaDaPauta,
                dividir: dividirPauta,
              }
            : undefined,
          pessoaDoCatalogo: (id) => !!d.pessoas.find((p) => p.id === id)?.catalogo_id,
          renomear: revisao.revisando && pode.aprovar ? abrirPessoa('renomear') : undefined,
          fundir: revisao.revisando && pode.fundir ? abrirPessoa('fundir') : undefined,
          edicao: edicao && conteudoDaEdicao ? { chave: edicao.chave, conteudo: conteudoDaEdicao } : null,
          marcas,
        }
      : undefined

  useAtalhos([
    { tecla: 'Espaço ou K', acao: 'Tocar e pausar', grupo: GRUPO, casa: (e) => tecla(e, ' ', 'k'), executar: alternar },
    { tecla: 'L', acao: 'Tocar; de novo, 2×; de novo, 4×', grupo: GRUPO, casa: (e) => tecla(e, 'l'), executar: tocarMaisRapido },
    {
      tecla: 'J',
      acao: 'Recuar 5 s',
      grupo: GRUPO,
      casa: (e) => tecla(e, 'j'),
      executar: () => saltarPara((player.current?.currentTime ?? 0) - SALTO_LONGO_S),
    },
    { tecla: '← →', acao: 'Recuar e avançar 1 s', grupo: GRUPO, ...recuarOuAvancar(SALTO_CURTO_S) },
    { tecla: 'Shift + ← →', acao: 'Recuar e avançar 5 s', grupo: GRUPO, ...recuarOuAvancar(SALTO_LONGO_S) },
    {
      tecla: ', .',
      acao: 'Quadro anterior e seguinte, com o vídeo pausado',
      grupo: GRUPO,
      casa: (e) => e.key === ',' || e.key === '.',
      // O `seeked` do player grava o novo instante no endereço.
      executar: (e) => {
        const el = player.current
        if (!el || !el.paused || !fps) return
        saltarPara(el.currentTime + (e.key === ',' ? -1 : 1) / fps)
      },
    },
    { tecla: 'F', acao: 'Tela cheia', grupo: GRUPO, casa: (e) => tecla(e, 'f'), executar: telaCheia },
    { tecla: '← →', acao: 'Numa faixa: passar de ocorrência (o player não anda)', grupo: GRUPO_DA_LINHA },
    { tecla: 'Enter', acao: 'Numa faixa: saltar à ocorrência', grupo: GRUPO_DA_LINHA },
    {
      tecla: ']',
      acao: 'Recolher e abrir o inspetor',
      grupo: GRUPO_DO_INSPETOR,
      casa: (e) => e.key === ']',
      executar: () => setInspetorAberto((a) => !a),
    },
    ...(pode.editar
      ? [
          {
            tecla: 'E',
            acao: 'Revisar o vídeo e, dentro da revisão, aprová-la',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'e'),
            executar: revisao.alternar,
          },
          {
            tecla: 'Ctrl + Z',
            acao: 'Desfazer a última correção sua neste vídeo',
            grupo: GRUPO_DA_CATALOGACAO,
            ctrl: true,
            // Ctrl+Shift+Z é o refazer de outros programas: aqui não desfaz.
            casa: (e: KeyboardEvent) => tecla(e, 'z') && !e.shiftKey,
            executar: () => void revisao.desfazer(),
          },
        ]
      : []),
    ...(revisao.revisando && d && catalogoPronto
      ? [
          {
            tecla: 'M',
            acao: 'Marcar a pauta em foco para juntar',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'm'),
            executar: () => alternarMarcaDaPauta(selecionado),
          },
          {
            tecla: 'U',
            acao: 'Juntar as pautas marcadas',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'u'),
            executar: juntarMarcadas,
          },
          {
            tecla: 'D',
            acao: 'Dividir a pauta em foco no ponto do player',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'd'),
            executar: () => dividirPauta(selecionado),
          },
        ]
      : []),
    ...(d && catalogoPronto
      ? [
          {
            tecla: 'F2',
            acao: 'Corrigir o item selecionado',
            grupo: GRUPO_DA_CORRECAO,
            casa: (e: KeyboardEvent) => e.key === 'F2',
            // Com a correção aberta, o F2 e o Del (vindos de uma alça ou de um botão) não a descartam.
            executar: () => {
              if (!edicao) corrigirItem(selecionado)
            },
          },
          {
            tecla: 'Del',
            acao: 'Não é isto: remover a pessoa ou o objeto do item selecionado',
            grupo: GRUPO_DA_CORRECAO,
            casa: (e: KeyboardEvent) => e.key === 'Delete',
            executar: () => {
              if (!edicao) removerItem(selecionado)
            },
          },
        ]
      : []),
  ])

  // A faixa do item com as alças aparece mesmo desligada nos chips.
  const faixaDasAlcas = edicao?.modo === 'editar' ? tipoDaChave(edicao.chave) : null
  const visiveis = faixas?.filter((f) => ligadas.has(f.chave) || f.chave === faixaDasAlcas)
  const erroDoPlayer = reproducao.isError ? codigoDoErro(reproducao.error) : falhaDaMidia
  const sessaoCaiu = reproducao.error instanceof SessaoExpirada

  return (
    <NomesDoCatalogo.Provider value={api.nomes}>
      <div className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto bg-canvas lg:flex-row lg:overflow-hidden">
        <section aria-label="Vídeo" className="flex min-w-0 shrink-0 flex-col bg-background lg:min-h-0 lg:flex-1 lg:shrink lg:overflow-y-auto">
          <BarraDoVideo
            job={job}
            versaoDoPipeline={d ? (d.versao_pipeline ?? null) : undefined}
            manifesto={d?.manifesto_do_pipeline}
            pode={pode}
            revisao={revisao}
            passadas={passadas.data ?? []}
            comparandoCom={comparandoCom}
            aoComparar={setComparandoCom}
            aoAbrirDialogo={setDialogo}
          />
          {job.etapa_atual && (job.estado === 'analisando' || finalizando(job)) && (
            <p role="status" className="shrink-0 border-b px-3 py-1.5 text-sm text-andamento">
              {`${reprocessou ? 'Reprocessando: ' : ''}${nomeDaEtapa(job.etapa_atual)} em andamento.`}
              {reprocessou && job.estado === 'analisando' && ' A Decupagem está sendo refeita e volta quando a análise terminar.'}
            </p>
          )}
          {/* O vídeo não tem `controls`: a tela cheia leva o transporte junto. Fora dela, `contents` deixa
              a moldura e o transporte no layout da seção, com o mesmo tamanho. */}
          <div ref={moldura} className="contents [&:fullscreen]:flex [&:fullscreen]:flex-col [&:fullscreen]:bg-background">
            <div className="relative flex aspect-video shrink-0 bg-black lg:aspect-auto lg:min-h-32 lg:flex-1 lg:shrink [:fullscreen>&]:aspect-auto [:fullscreen>&]:min-h-0 [:fullscreen>&]:flex-1">
              {erroDoPlayer && !sessaoCaiu ? (
                <AvisoDeFalha
                  className="m-auto max-w-sm"
                  mensagem="Não foi possível carregar o vídeo. Tente de novo em instantes."
                  codigo={erroDoPlayer}
                  aoTentar={() => {
                    setFalhaDaMidia(null)
                    void reproducao.refetch()
                  }}
                />
              ) : (
                <video
                  ref={player}
                  src={reproducao.data?.url}
                  aria-label="Player"
                  className="size-full min-h-0 object-contain"
                  onClick={alternar}
                  onError={aoFalharOPlayer}
                  onLoadedMetadata={(e) => {
                    const el = e.currentTarget
                    if (Number.isFinite(el.duration)) setDuracaoMs(el.duration * 1000)
                    if (retomarEm.current !== null) {
                      el.currentTime = retomarEm.current
                      retomarEm.current = null
                    }
                    instante.definir(el.currentTime * 1000)
                  }}
                  onTimeUpdate={(e) => aoAtualizarOTempo(e.currentTarget)}
                  onPlay={() => setTocando(true)}
                  onPause={() => {
                    setTocando(false)
                    gravarNoEndereco()
                  }}
                  onSeeked={gravarNoEndereco}
                  onRateChange={(e) => setVelocidade(e.currentTarget.playbackRate)}
                />
              )}
            </div>
            <Transporte
              job={job}
              instante={instante}
              duracaoMs={duracaoMs}
              tocando={tocando}
              velocidade={velocidade}
              aoSilenciar={(mudo) => {
                if (player.current) player.current.muted = mudo
              }}
              aoMudarVolume={(volume) => {
                if (player.current) player.current.volume = volume
              }}
              aoAlternar={alternar}
              aoSaltar={(passo) => saltarPara((player.current?.currentTime ?? 0) + passo)}
              aoMudarVelocidade={mudarVelocidade}
              aoTelaCheia={telaCheia}
            />
          </div>
          {decupagem.isError && !(decupagem.error instanceof SessaoExpirada) && (
            <AvisoDeFalha
              className="m-2 shrink-0"
              mensagem="Não foi possível carregar a linha do tempo. Tente de novo em instantes."
              codigo={codigoDoErro(decupagem.error)}
              aoTentar={() => void decupagem.refetch()}
            />
          )}
          {catalogo.isError && !(catalogo.error instanceof SessaoExpirada) && (
            <AvisoDeFalha
              className="m-2 shrink-0"
              mensagem="Não foi possível carregar as opções de correção; corrigir fica indisponível. Tente de novo em instantes."
              codigo={codigoDoErro(catalogo.error)}
              aoTentar={() => void catalogo.refetch()}
            />
          )}
          {faixas && visiveis && (
            <>
              <ChipsDasFaixas
                faixas={faixas}
                ligadas={ligadas}
                aoAlternar={(chave) =>
                  setLigadas((l) => {
                    const novas = new Set(l)
                    if (!novas.delete(chave)) novas.add(chave)
                    return novas
                  })
                }
              />
              <LinhaDoTempo
                faixas={visiveis}
                cortesMs={job.cortes_ms}
                duracaoMs={duracaoDaLinhaMs}
                instante={instante}
                selecionada={selecionada}
                alcas={alcas}
                aoSaltar={saltarParaMs}
                aoSelecionar={(chave) => abrirItem(chave, true)}
              />
            </>
          )}
        </section>
        {comparandoCom ? (
          <ComparacaoDePassada api={cliente} id={job.id} passadaId={comparandoCom} aoSaltar={saltarParaMs} aoFechar={() => setComparandoCom(null)} />
        ) : inspetorAberto ? (
          <Inspetor
            decupagem={d}
            carregando={concluido && decupagem.isPending}
            itens={itens}
            instante={instante}
            duracaoMs={duracaoDaLinhaMs}
            secao={secao}
            aoTrocarSecao={setSecao}
            selecionada={selecionada}
            detalhe={detalhe && !!selecionado}
            aoAbrir={abrirItem}
            aoMover={selecionar}
            aoFecharDetalhe={() => {
              setDetalhe(false)
              fecharEdicao()
            }}
            aoSaltar={saltarParaMs}
            aoTocarTrecho={tocarTrecho}
            urlDoQuadro={urlDoQuadro}
            acoes={acoes}
            aviso={aviso}
            acima={
              revisao.revisando ? (
                <>
                  {sugestoes.data ? (
                    <Sugestoes
                      sugestoes={sugestoes.data}
                      decupagem={d}
                      api={cliente}
                      aoSaltar={saltarParaMs}
                      aoResolver={(id) => {
                        consultas.setQueryData(chaveDasSugestoes, (l: Sugestao[] | undefined) => l?.filter((x) => x.id !== id))
                        void consultas.invalidateQueries({ queryKey: chaveDoVideo(job.id, 'decupagem') })
                        void consultas.invalidateQueries({ queryKey: chaveDoVideo(job.id, 'historico') })
                      }}
                      aoFalhar={() => void consultas.invalidateQueries({ queryKey: chaveDasSugestoes })}
                      aoAvisar={mostrarAviso}
                    />
                  ) : null}
                  {marcadasNaDecupagem > 0 ? (
                    <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm">
                      <span className="mr-auto">
                        {marcadasNaDecupagem} {marcadasNaDecupagem === 1 ? 'pauta marcada' : 'pautas marcadas'} para juntar
                      </span>
                      <BotaoComDica dica="U" variant="outline" onClick={juntarMarcadas}>
                        Juntar as pautas marcadas
                      </BotaoComDica>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setPautasMarcadas(new Set())}>
                        Limpar marcas
                      </Button>
                    </div>
                  ) : null}
                  {catalogoPronto && estrutura ? (
                    <div className="border-b border-border p-3">
                      <FormularioDeCorrecao
                        key={estrutura.modo === 'juntar' ? `juntar:${estrutura.pautas.map((p) => p.id).join('+')}` : `dividir:${estrutura.pauta.id}:${estrutura.em_ms}`}
                        editor={estrutura.modo === 'juntar' ? editorDeJuncao(estrutura.pautas, catalogoPronto) : editorDeDivisao(estrutura.pauta, estrutura.em_ms, catalogoPronto)}
                        rotulo={estrutura.modo === 'juntar' ? `Juntar ${estrutura.pautas.length} pautas` : `Dividir ${estrutura.pauta.titulo} em ${relogio(estrutura.em_ms)}`}
                        limiteDoMotivo={catalogoPronto.limites.motivo}
                        aoSalvar={gravarEstrutura}
                        aoCancelar={() => setEstrutura(null)}
                      />
                    </div>
                  ) : null}
                </>
              ) : null
            }
            indexando={pode.editar && !!historico.data && aindaIndexando(historico.data)}
            aoRecolher={() => setInspetorAberto(false)}
          />
        ) : (
          <div className="flex shrink-0 justify-center bg-background p-1 lg:w-10 lg:flex-col lg:justify-start">
            <BotaoDeIcone rotulo="Abrir o inspetor" atalho="]" onClick={() => setInspetorAberto(true)}>
              <IconLayoutSidebarRightExpand size={18} stroke={1.75} aria-hidden />
            </BotaoDeIcone>
          </div>
        )}
      </div>
      <DialogosDoVideo
        aberto={dialogo}
        job={job}
        aoFechar={() => setDialogo(null)}
        aoReprocessar={(novo, etapa) => {
          setDialogo(null)
          aoReprocessar(novo, etapa)
        }}
        aoMandarParaLixeira={() => navegar(ACERVO)}
      />
    </NomesDoCatalogo.Provider>
  )
}

// ---------- barra do vídeo ----------

/** Nome e ações do vídeo, acima do player (MAM_DESIGN_SYSTEM 10): baixar, quem acessou e o menu. */
function BarraDoVideo({
  job,
  versaoDoPipeline,
  manifesto,
  pode,
  revisao,
  passadas,
  comparandoCom,
  aoComparar,
  aoAbrirDialogo,
}: {
  job: Job
  /** `undefined` sem a decupagem; `null` na decupagem anterior à versão fixa do pipeline. */
  versaoDoPipeline: string | null | undefined
  manifesto: unknown
  pode: Permissoes
  revisao: Revisao
  passadas: ResumoDaPassada[]
  comparandoCom: string | null
  aoComparar: (id: string | null) => void
  aoAbrirDialogo: (d: DialogoDoVideo) => void
}) {
  const api = useApi()
  const [baixando, setBaixando] = useState<'video' | 'json' | null>(null)
  const [falha, setFalha] = useState<{ de: 'video' | 'json'; codigo: string } | null>(null)
  const concluido = job.estado === 'concluido'
  const titulo = [job.programa, job.data_exibicao ? dataDeExibicao(job.data_exibicao) : null].filter(Boolean).join(' · ')
  const auditoria = enderecoDaAuditoria(filtrosDeQuemAcessou(job.id))
  const podeReprocessar = pode.reprocessar && concluido && !finalizando(job)
  const podeApagar = pode.apagar && ESTADOS_QUE_VAO_PARA_A_LIXEIRA.includes(job.estado)

  async function baixar(de: 'video' | 'json') {
    setFalha(null)
    setBaixando(de)
    try {
      if (de === 'video') baixarPelaUrl((await api.job(job.id).baixarVideo()).url)
      else baixarDecupagem(job.nome, await api.job(job.id).baixarDecupagem())
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) setFalha({ de, codigo: codigoDoErro(e) })
    } finally {
      setBaixando(null)
    }
  }

  return (
    <>
      <div className="flex h-10 shrink-0 items-center gap-3 border-b px-3">
        <div className="flex min-w-0 flex-1 items-baseline gap-2">
          <h1 className="truncate text-sm font-semibold" title={job.nome}>
            {job.nome}
          </h1>
          {titulo && <span className="hidden shrink-0 text-xs text-muted-foreground md:inline">{titulo}</span>}
          {versaoDoPipeline !== undefined && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={0} className="hidden shrink-0 rounded-xs border border-strong px-1.5 text-xs whitespace-nowrap text-muted-foreground xl:inline">
                  Pipeline {versaoDoPipeline ?? 'anterior à versão'}
                </span>
              </TooltipTrigger>
              <TooltipContent collisionPadding={8} className="max-w-md font-mono whitespace-pre-wrap">
                {manifesto ? JSON.stringify(manifesto, null, 1) : 'Decupagem feita antes da versão fixa do pipeline'}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
        <div className="-mr-1.5 flex shrink-0 items-center gap-0.5">
          {passadas.length > 0 && <SeletorDePassada passadas={passadas} valor={comparandoCom} aoEscolher={aoComparar} />}
          {pode.editar && concluido && <ControlesDaRevisao revisao={revisao} />}
          {concluido && (
            <BotaoDeIcone rotulo="Baixar vídeo" aria-busy={baixando === 'video'} disabled={baixando === 'video'} onClick={() => void baixar('video')}>
              <IconDownload size={18} stroke={1.75} aria-hidden />
            </BotaoDeIcone>
          )}
          {concluido && (
            <BotaoDeIcone rotulo="Baixar decupagem (JSON)" aria-busy={baixando === 'json'} disabled={baixando === 'json'} onClick={() => void baixar('json')}>
              <IconFileDownload size={18} stroke={1.75} aria-hidden />
            </BotaoDeIcone>
          )}
          {pode.verAuditoria && (
            <Tooltip>
              <TooltipTrigger asChild>
                <a
                  href={auditoria}
                  aria-label="Quem acessou"
                  onClick={(e) => seguir(e, auditoria)}
                  className="inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <IconEye size={18} stroke={1.75} aria-hidden />
                </a>
              </TooltipTrigger>
              <TooltipContent collisionPadding={8}>Quem acessou</TooltipContent>
            </Tooltip>
          )}
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label="Mais ações"
                    className="inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <IconDots size={18} stroke={1.75} aria-hidden />
                  </button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent collisionPadding={8}>Mais ações</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-64">
              {podeReprocessar && (
                <DropdownMenuItem onSelect={() => aoAbrirDialogo('reprocessar')}>
                  <IconRefresh size={16} stroke={1.75} aria-hidden /> Reprocessar…
                </DropdownMenuItem>
              )}
              {podeApagar && (
                <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => aoAbrirDialogo('lixeira')}>
                  <IconTrash size={16} stroke={1.75} aria-hidden /> Mandar para a lixeira…
                </DropdownMenuItem>
              )}
              {(podeReprocessar || podeApagar) && <DropdownMenuSeparator />}
              {/* Revisão, histórico, trecho, sugestões e comparação de passadas chegam na fase 5. */}
              <DropdownMenuItem asChild>
                <a href={naInterfaceAtual()}>
                  <IconExternalLink size={16} stroke={1.75} aria-hidden />
                  {pode.editar ? 'Revisar e ver o histórico na interface atual' : 'Abrir na interface atual'}
                </a>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {falha && (
        <AvisoDeFalha
          className="m-2 shrink-0"
          mensagem={falha.de === 'video' ? 'Não foi possível preparar o download. Tente de novo.' : 'Não foi possível baixar a decupagem. Tente de novo em instantes.'}
          codigo={falha.codigo}
          aoTentar={() => void baixar(falha.de)}
        />
      )}
    </>
  )
}

/** Revisar (E) e, dentro da revisão, o que só ela tem: Catalogando, Desfazer (Ctrl+Z) e Aprovar Revisão (E). */
function ControlesDaRevisao({ revisao }: { revisao: Revisao }) {
  const { revisando } = revisao
  return (
    <div className="mr-1 flex shrink-0 items-center gap-1">
      {revisando && (
        <>
          <span className="hidden text-xs font-semibold text-andamento sm:inline">Catalogando</span>
          <BotaoDeIcone rotulo="Desfazer" atalho="Ctrl+Z" disabled={!revisao.temParaDesfazer} onClick={() => void revisao.desfazer()}>
            <IconArrowBackUp size={18} stroke={1.75} aria-hidden />
          </BotaoDeIcone>
        </>
      )}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button size="sm" variant={revisando ? 'default' : 'secondary'} onClick={revisao.alternar}>
            {revisando ? 'Aprovar Revisão' : 'Revisar'}
          </Button>
        </TooltipTrigger>
        <TooltipContent collisionPadding={8}>
          {revisando ? 'Aprovar Revisão' : 'Revisar'}
          <Kbd>E</Kbd>
        </TooltipContent>
      </Tooltip>
    </div>
  )
}

// ---------- transporte ----------

/** O relógio do player, que se renderiza sozinho a cada segundo. */
function Relogio({ instante, duracaoMs }: { instante: Instante; duracaoMs: number }) {
  const agora = useNoInstante(instante, relogio)
  return (
    <span className="font-mono text-sm whitespace-nowrap tabular-nums">
      {`${agora} / ${relogio(duracaoMs)}`}
    </span>
  )
}

function Transporte({
  job,
  instante,
  duracaoMs,
  tocando,
  velocidade,
  aoSilenciar,
  aoMudarVolume,
  aoAlternar,
  aoSaltar,
  aoMudarVelocidade,
  aoTelaCheia,
}: {
  job: Job
  instante: Instante
  duracaoMs: number
  tocando: boolean
  velocidade: number
  aoSilenciar: (mudo: boolean) => void
  aoMudarVolume: (volume: number) => void
  aoAlternar: () => void
  aoSaltar: (segundos: number) => void
  aoMudarVelocidade: (v: number) => void
  aoTelaCheia: () => void
}) {
  const fps = job.taxa_de_quadros ?? null
  const origem = job.timecode_origem ?? null
  const tc = useNoInstante(instante, (ms) => (origem && fps ? timecodeNoInstante(origem, fps, ms) : null))
  const [copiado, setCopiado] = useState<string | null>(null)
  const [mudo, setMudo] = useState(false)
  const [volume, setVolume] = useState(1)
  const fimDoAviso = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(fimDoAviso.current), [])

  async function copiar(texto: string, aviso: string) {
    try {
      await navigator.clipboard.writeText(texto)
    } catch {
      return
    }
    setCopiado(aviso)
    clearTimeout(fimDoAviso.current)
    fimDoAviso.current = setTimeout(() => setCopiado(null), AVISO_CURTO_MS)
  }

  const link = () => {
    const busca = new URLSearchParams(location.search).get('busca')
    return location.origin + enderecoDoVideo(job.id, Math.floor(instante.ms() / 1000), busca)
  }

  return (
    <div className="flex h-10 shrink-0 items-center gap-0.5 overflow-x-auto border-t px-1 sm:gap-1 sm:px-2">
      <BotaoDeIcone rotulo="Recuar 5 s" atalho="J" onClick={() => aoSaltar(-SALTO_LONGO_S)}>
        <IconArrowBackUp size={18} stroke={1.75} aria-hidden />
      </BotaoDeIcone>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={aoAlternar}
            aria-label={tocando ? 'Pausar' : 'Tocar'}
            className="flex size-8 shrink-0 items-center justify-center rounded-sm bg-foreground text-background hover:bg-foreground/90"
          >
            {tocando ? <IconPlayerPause size={18} stroke={2} aria-hidden /> : <IconPlayerPlay size={18} stroke={2} aria-hidden />}
          </button>
        </TooltipTrigger>
        <TooltipContent collisionPadding={8}>{tocando ? 'Pausar' : 'Tocar'} (Espaço)</TooltipContent>
      </Tooltip>
      <BotaoDeIcone rotulo="Avançar 5 s" atalho="Shift →" onClick={() => aoSaltar(SALTO_LONGO_S)}>
        <IconArrowForwardUp size={18} stroke={1.75} aria-hidden />
      </BotaoDeIcone>
      <div className="ml-1 hidden shrink-0 items-center gap-0.5 rounded-sm bg-input p-0.5 sm:flex" role="group" aria-label="Velocidade">
        {VELOCIDADES.map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={velocidade === v}
            onClick={() => aoMudarVelocidade(v)}
            className={cn(
              'h-6 rounded-xs px-1.5 font-mono text-xs tabular-nums',
              velocidade === v ? 'bg-selected text-link' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {`${v}×`}
          </button>
        ))}
      </div>
      <span className="ml-2 shrink-0">
        <Relogio instante={instante} duracaoMs={duracaoMs} />
      </span>
      {tc && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`Copiar o timecode ${tc}`}
              onClick={() => void copiar(tc, 'Timecode copiado')}
              className="ml-2 hidden shrink-0 rounded-xs border border-strong px-1.5 py-0.5 font-mono text-xs whitespace-nowrap text-muted-foreground tabular-nums hover:text-foreground md:inline"
            >
              {`TC ${tc}`}
            </button>
          </TooltipTrigger>
          <TooltipContent collisionPadding={8}>Copiar o timecode de origem</TooltipContent>
        </Tooltip>
      )}
      <span role="status" className="ml-2 shrink-0 text-xs whitespace-nowrap text-muted-foreground">
        {copiado ?? ''}
      </span>
      <div className="ml-auto flex shrink-0 items-center gap-0.5">
        <BotaoDeIcone rotulo="Copiar o link neste tempo" onClick={() => void copiar(link(), 'Link copiado')}>
          <IconLink size={18} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
        <BotaoDeIcone
          rotulo={mudo ? 'Ligar o som' : 'Silenciar'}
          onClick={() => {
            aoSilenciar(!mudo)
            setMudo(!mudo)
          }}
        >
          {mudo ? <IconVolumeOff size={18} stroke={1.75} aria-hidden /> : <IconVolume size={18} stroke={1.75} aria-hidden />}
        </BotaoDeIcone>
        <input
          type="range"
          aria-label="Volume"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(e) => {
            const v = Number(e.currentTarget.value)
            aoMudarVolume(v)
            setVolume(v)
          }}
          className="hidden w-20 accent-primary lg:block"
        />
        <BotaoDeIcone rotulo="Tela cheia" atalho="F" onClick={aoTelaCheia}>
          <IconMaximize size={18} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
      </div>
    </div>
  )
}
