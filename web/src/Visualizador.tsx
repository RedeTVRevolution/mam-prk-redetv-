import { ActionIcon, Box, Button, Group, Indicator, Kbd, Paper, Slider, Stack, Text, Tooltip } from '@mantine/core'
import {
  IconArrowBackUp,
  IconDownload,
  IconHistory,
  IconMaximize,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconX,
  IconVolume,
  IconVolumeOff,
} from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { type ClienteDaApi, codigoDoErro, ConflitoNaApi, PedidoInvalido, SessaoExpirada } from './api.ts'
import { type CatalogoDeCorrecoes, rotuloDe } from './catalogo.ts'
import { useAtalhos } from './atalhos.ts'
import { baixarDecupagem } from './baixar.ts'
import {
  aindaIndexando,
  desfazivel,
  editorDeNovaAparicao,
  editorDoItem,
  itemDaCorrecao,
  marcasDosItens,
  type Pedido,
  motivoDaRemocao,
  pedidoDeRemocao,
  podeRemover,
} from './catalogacao.ts'
import { ConfirmacaoDeRemocao, FormularioDeCorrecao } from './FormularioDeCorrecao.tsx'
import { dataDeExibicao, type Job } from './jobs.ts'
import { type AlcasDaCorrecao, FaixasDoVideo, type TrechoMarcado } from './FaixasDoVideo.tsx'
import { NomesDoCatalogo } from './nomesDoCatalogo.ts'
import { FormularioDoTrecho } from './FormularioDoTrecho.tsx'
import { ABAS_DO_TRECHO } from './trecho.ts'
import { type AbaDaGaveta, Gaveta } from './Gaveta.tsx'
import { ComparacaoDePassada, SeletorDePassada } from './ComparacaoDePassadas.tsx'
import { usePassadas } from './usePassadas.ts'
import { useSessaoDeRevisao } from './useSessaoDeRevisao.ts'
import { Sugestoes } from './Sugestoes.tsx'
import { type EdicaoNoPainel, Painel } from './Painel.tsx'
import { nomeDaEtapa } from './etapas.ts'
import { ReprocessarEtapa } from './ReprocessarEtapa.tsx'
import { QuadroDoObjeto, type ObjetoApontado } from './Inventario.tsx'
import { criarCacheDeQuadros } from './quadros.ts'
import { type Aba, abaDaChave, type ItemDoPainel, itensDoPainel, nomeNormalizado } from './painel.ts'
import { type Borda, duracaoDaLinha, faixasDoVisualizador, type Intervalo, relogio } from './linhaDoTempo.ts'
import { ALTURA_DA_BARRA, CORES } from './tema.ts'
import { timecodeNoInstante } from './timecode.ts'
import { enderecoDoVideo, navegar } from './rotas.ts'
import { consultaNova } from './busca.ts'
import {
  guardado,
  guardarResultado,
  lerResultado,
  momentoAtual,
  passoNoResultado,
  rotuloDaBusca,
  type VideoGuardado,
} from './resultadoDaBusca.ts'
import type { Decupagem, ItemDaFila, ItemDoHistorico, Reproducao, Sugestao } from './decupagem.ts'

const VELOCIDADES = [1, 2, 4]
const SALTO_CURTO_S = 1
const SALTO_LONGO_S = 5
const AVISO_DO_TC_MS = 1500

const GRUPO = 'Player'
const GRUPO_DA_LINHA = 'Linha do tempo'
const GRUPO_DA_CATALOGACAO = 'Catalogação'
const AVISO_DO_DESFAZER_MS = 5000
const INTERVALO_DA_INDEXACAO_MS = 2000
// O resultado refeito quando a sessão não o guardou: o teto de vídeos da página de busca.
const VIDEOS_DO_RESULTADO = 50
const GRUPO_DA_BUSCA = 'Busca'

/** O evento é de uma destas teclas (letras sem diferença de caixa). */
function tecla(e: KeyboardEvent, ...teclas: string[]): boolean {
  return teclas.includes(e.key.toLowerCase())
}

function tocar(player: HTMLVideoElement) {
  // O navegador recusa o play sem gesto ou com o arquivo ainda sem carregar: sem erro na tela.
  Promise.resolve(player.play()).catch(() => {})
}

/** O Visualizador: o vídeo com controles e atalhos próprios, o TC de origem e o endereço com o tempo. */
export default function Visualizador({
  api,
  job: jobInicial,
  t,
  busca = null,
  podeEditar,
  podeAprovar = false,
  podeReprocessar = false,
  intervaloDoAcompanhamentoMs = 5000,
  intervaloDaIndexacaoMs = INTERVALO_DA_INDEXACAO_MS,
}: {
  api: ClienteDaApi
  job: Job
  t: number | null
  /** O texto da busca de onde a pessoa chegou: ele liga a faixa "Busca" e o N. */
  busca?: string | null
  podeEditar: boolean
  podeAprovar?: boolean
  podeReprocessar?: boolean
  intervaloDoAcompanhamentoMs?: number
  /** De quanto em quanto a tela pergunta se a correção já entrou no índice. */
  intervaloDaIndexacaoMs?: number
}) {
  // O Job muda quando a pessoa reprocessa: o que a API devolveu vale mais que o da abertura.
  const [job, setJob] = useState(jobInicial)
  const [escolhendo, setEscolhendo] = useState(false)
  const [acompanhando, setAcompanhando] = useState(false)
  const [reproducao, setReproducao] = useState<Reproducao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [tentativas, setTentativas] = useState(0)
  const player = useRef<HTMLVideoElement>(null)
  const moldura = useRef<HTMLDivElement>(null)
  const retomarEm = useRef<number | null>(t)
  const [atualMs, setAtualMs] = useState(0)
  const [duracaoMs, setDuracaoMs] = useState((job.duracao_s ?? 0) * 1000)
  const [tocando, setTocando] = useState(false)
  const [velocidade, setVelocidade] = useState(1)
  const [volume, setVolume] = useState(1)
  const [mudo, setMudo] = useState(false)
  const [copiado, setCopiado] = useState(false)
  const [falhaDoJson, setFalhaDoJson] = useState<string | null>(null)
  const [decupagem, setDecupagem] = useState<Decupagem | null>(null)
  const [falhaDaDecupagem, setFalhaDaDecupagem] = useState<string | null>(null)
  const [cargasDaDecupagem, setCargasDaDecupagem] = useState(0)
  const [selecionada, setSelecionada] = useState<string | null>(null)
  const [aba, setAba] = useState<Aba>('agora')
  const [pessoasAbertas, setPessoasAbertas] = useState<ReadonlySet<string>>(new Set())
  const [catalogando, setCatalogando] = useState(false)
  const [temParaDesfazer, setTemParaDesfazer] = useState(false)
  const [catalogo, setCatalogo] = useState<CatalogoDeCorrecoes | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [objetoApontado, setObjetoApontado] = useState<ObjetoApontado | null>(null)
  const [emEdicao, setEmEdicao] = useState<{ chave: string; modo: 'editar' | 'remover' | 'acrescentar' } | null>(null)
  // Os tempos que as alças da linha do tempo ajustaram na correção aberta.
  const [temposDaAlca, setTemposDaAlca] = useState<Intervalo | null>(null)
  const salvarDasAlcas = useRef<(() => void) | null>(null)
  // O trecho marcado com I e O; `descrevendo` abre o campo único com o tipo em abas.
  const [trecho, setTrecho] = useState<{ inicio_ms: number; fim_ms: number | null } | null>(null)
  const [descrevendo, setDescrevendo] = useState(false)
  const salvarDoTrecho = useRef<(() => void) | null>(null)
  const [historico, setHistorico] = useState<ItemDoHistorico[]>([])
  const [fila, setFila] = useState<ItemDaFila[]>([])
  const [sugestoes, setSugestoes] = useState<Sugestao[]>([])
  const [cargasDeSugestoes, setCargasDeSugestoes] = useState(0)
  const [falhaNoHistorico, setFalhaNoHistorico] = useState(false)
  const [gavetaAberta, setGavetaAberta] = useState(false)
  const [abaDaGaveta, setAbaDaGaveta] = useState<AbaDaGaveta>('historico')
  const avisoDoDesfazer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(avisoDoDesfazer.current), [])
  // Dois Ctrl+Z seguidos não pedem o mesmo desfazer duas vezes.
  const desfazendo = useRef(false)
  // "Reproduzir trecho": onde o player para sozinho.
  const pararEm = useRef<number | null>(null)
  const avisoDoTc = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(avisoDoTc.current), [])

  useEffect(() => {
    let ativo = true
    api.job(job.id).reproducao().then(
      (r) => {
        if (ativo) {
          setErro(null)
          setReproducao(r)
        }
      },
      (e: unknown) => {
        if (!ativo || e instanceof SessaoExpirada) return
        setErro(codigoDoErro(e))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, tentativas])

  const concluido = job.estado === 'concluido'
  // Um cliente só por Job: `api.job()` monta um objeto novo a cada chamada, e o efeito que
  // depende dele pediria de novo a cada render.
  const clienteDoJob = useMemo(() => api.job(job.id), [api, job.id])
  const passadas = usePassadas(clienteDoJob, concluido)
  // A sessão de revisão (#251) vale no modo de catalogação; a pessoa não vê nada dela.
  useSessaoDeRevisao(clienteDoJob, podeEditar && catalogando, tocando)
  const [comparandoCom, setComparandoCom] = useState<string | null>(null)
  useEffect(() => {
    if (!concluido) return
    let ativo = true
    api.job(job.id).decupagem().then(
      (d) => {
        if (!ativo) return
        setFalhaDaDecupagem(null)
        setDecupagem(d)
      },
      (e: unknown) => {
        if (ativo && !(e instanceof SessaoExpirada)) setFalhaDaDecupagem(codigoDoErro(e))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, concluido, cargasDaDecupagem])

  // Depois do pedido, vê de tempos em tempos se as etapas já terminaram. Entre uma etapa e a
  // seguinte o `etapa_atual` fica vazio; a indexação, a última, só sai de `pendente` no fim.
  const emAndamento =
    job.estado === 'analisando' || Boolean(job.etapa_atual) || job.indexacao?.estado === 'pendente'
  useEffect(() => {
    if (!acompanhando) return
    if (!emAndamento) {
      // oxlint-disable-next-line react/set-state-in-effect
      setAcompanhando(false)
      // Identificação e quadros-chave regravam a Decupagem com o Job sempre `concluido`.
      setCargasDaDecupagem((n) => n + 1)
      return
    }
    const intervalo = setInterval(() => {
      api.job(job.id).detalhe().then(setJob, () => {})
    }, intervaloDoAcompanhamentoMs)
    return () => clearInterval(intervalo)
  }, [api, job.id, acompanhando, emAndamento, intervaloDoAcompanhamentoMs])

  function aoReprocessar(novo: Job, etapa: string) {
    setJob(novo)
    setEscolhendo(false)
    setAcompanhando(true)
    // Com a análise, a Decupagem antiga some até a nova terminar.
    if (etapa === 'analise') setDecupagem(null)
  }

  const fotosDoNome = useCallback((pessoaId: string) => api.job(job.id).fotosDoNome(pessoaId), [api, job.id])

  // O catálogo de correções (rótulos e vocabulários) só serve a quem edita.
  useEffect(() => {
    if (!podeEditar) return
    let ativo = true
    api.job(job.id).catalogo().then(
      (c) => {
        if (ativo) setCatalogo(c)
      },
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, podeEditar])

  // As marcas "corrigido" e "aguardando o Curador" vêm do histórico, recarregado a cada decupagem nova.
  useEffect(() => {
    if (!podeEditar || !decupagem) return
    let ativo = true
    // Um não espera o outro: sem a fila, as marcas do histórico continuam valendo.
    void Promise.allSettled([api.job(job.id).historico(), api.job(job.id).fila()]).then(([h, f]) => {
      if (!ativo) return
      if (h.status === 'fulfilled') setHistorico(h.value)
      if (f.status === 'fulfilled') setFila(f.value)
      setFalhaNoHistorico(h.status === 'rejected' || f.status === 'rejected')
    })
    return () => {
      ativo = false
    }
  }, [api, job.id, podeEditar, decupagem])

  // Uma correção nova entra no índice depois de gravada: pergunta de novo até ela confirmar.
  useEffect(() => {
    if (!podeEditar || !aindaIndexando(historico)) return
    let ativo = true
    const espera = setTimeout(() => {
      api.job(job.id).historico().then(
        (h) => ativo && setHistorico(h),
        // Uma falha não encerra a espera: a cópia do histórico agenda a próxima pergunta.
        () => ativo && setHistorico((h) => [...h]),
      )
    }, intervaloDaIndexacaoMs)
    return () => {
      ativo = false
      clearTimeout(espera)
    }
  }, [api, job.id, podeEditar, historico, intervaloDaIndexacaoMs])

  // O resultado da busca de onde a pessoa veio: o da sessão, ou a busca refeita.
  const [resultadoDaBusca, setResultadoDaBusca] = useState<VideoGuardado[] | null>(null)
  // O código da falha da busca refeita: o N avisa em vez de esperar para sempre.
  const [buscaFalhou, setBuscaFalhou] = useState<string | null>(null)
  useEffect(() => {
    // Sem busca no endereço, a faixa e o N somem.
    // oxlint-disable-next-line react/set-state-in-effect
    setResultadoDaBusca(null)
    setBuscaFalhou(null)
    if (!busca) return
    const guardada = lerResultado(busca)
    if (guardada) {
      setResultadoDaBusca(guardada)
      return
    }
    let ativo = true
    api.buscar(consultaNova(busca), VIDEOS_DO_RESULTADO).then(
      (r) => {
        if (!ativo) return
        const videos = guardado(r.videos)
        guardarResultado(busca, videos)
        setResultadoDaBusca(videos)
      },
      (erro) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setBuscaFalhou(codigoDoErro(erro))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, busca])
  const momentosDaBusca = useMemo(
    () => resultadoDaBusca?.find((v) => v.job_id === job.id)?.momentos ?? [],
    [resultadoDaBusca, job.id],
  )

  // As sugestões saem da decupagem entregue: a lista vem de novo a cada decupagem nova e ao ligar o modo.
  useEffect(() => {
    if (!podeEditar || !catalogando || !decupagem) return
    let ativo = true
    api.job(job.id).sugestoes().then(
      (lista) => ativo && setSugestoes(lista),
      () => ativo && setSugestoes([]),
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, podeEditar, catalogando, decupagem, cargasDeSugestoes])

  const itens = useMemo(() => (decupagem ? itensDoPainel(decupagem) : []), [decupagem])
  const marcas = useMemo(
    () => (decupagem && podeEditar ? marcasDosItens(decupagem, itens, historico) : undefined),
    [decupagem, itens, historico, podeEditar],
  )

  function fecharEdicao() {
    setEmEdicao(null)
    setTemposDaAlca(null)
  }

  /** Grava os pedidos em sequência com o motivo; devolve o erro que fica no formulário, ou `null`. */
  async function gravar(pedidos: Pedido[], motivo: string): Promise<string | null> {
    if (!decupagem) return null
    let gravadas = 0
    try {
      let versao = decupagem.versao_decupagem
      for (const { pessoa_do_nome, ...p } of pedidos) {
        let item_id = p.item_id
        if (pessoa_do_nome) {
          // A pessoa acabou de ser acrescentada: o id dela está na decupagem recarregada.
          const atual = await api.job(job.id).decupagem()
          const alvo = nomeNormalizado(pessoa_do_nome)
          const pessoa = atual.pessoas.find((x) => nomeNormalizado(x.nome) === alvo)
          if (!pessoa) throw new PedidoInvalido('A pessoa acrescentada não apareceu na decupagem. Marque a menção pelo painel.')
          item_id = pessoa.id
          versao = atual.versao_decupagem
        }
        await api.job(job.id).corrigir({ ...p, item_id, motivo, versao })
        gravadas += 1
      }
    } catch (e) {
      if (e instanceof SessaoExpirada) return null
      const mensagem =
        e instanceof ConflitoNaApi || e instanceof PedidoInvalido
          ? e.message
          : 'Não foi possível gravar a correção. Tente de novo em instantes.'
      // Com a decupagem mudada (ou parte já gravada), a tela recarrega e o formulário fecha.
      if (e instanceof ConflitoNaApi || gravadas > 0) {
        setCargasDaDecupagem((n) => n + 1)
        fecharEdicao()
        mostrarAviso(mensagem)
        return null
      }
      return mensagem
    }
    setCargasDaDecupagem((n) => n + 1)
    fecharEdicao()
    return null
  }

  function descartarTrecho() {
    setTrecho(null)
    setDescrevendo(false)
  }

  /** `I`: a entrada do trecho no tempo atual; uma saída que ficaria antes dela sai, e o campo fecha. */
  function marcarEntrada() {
    if (!catalogando) return
    const fim = trecho?.fim_ms != null && trecho.fim_ms >= atualMs ? trecho.fim_ms : null
    if (trecho?.fim_ms != null && fim === null) {
      setDescrevendo(false)
      mostrarAviso('A entrada passou da saída: marque a saída de novo (O).')
    }
    setTrecho({ inicio_ms: atualMs, fim_ms: fim })
  }

  /** `E`: liga e desliga o modo; o trecho marcado não sobrevive à saída do modo. */
  function alternarCatalogacao() {
    descartarTrecho()
    setCatalogando((c) => !c)
  }

  /** `O`: a saída do trecho no tempo atual, depois da entrada. */
  function marcarSaida() {
    if (!catalogando) return
    if (!trecho) {
      mostrarAviso('Marque a entrada antes (I).')
      return
    }
    if (atualMs < trecho.inicio_ms) {
      mostrarAviso('A saída fica depois da entrada: avance o vídeo e marque de novo (O).')
      return
    }
    setTrecho({ inicio_ms: trecho.inicio_ms, fim_ms: atualMs })
  }

  /** `A`: abre o campo do trecho marcado (entrada e saída). */
  function descreverTrecho() {
    if (!catalogando) return
    if (trecho?.fim_ms == null) {
      mostrarAviso('Marque a entrada e a saída do trecho antes (I e O).')
      return
    }
    fecharEdicao()
    setDescrevendo(true)
  }

  /** Grava a correção do trecho; com ela gravada, o trecho some. */
  async function gravarTrecho(pedidos: Pedido[], motivo: string): Promise<string | null> {
    const falha = await gravar(pedidos, motivo)
    if (!falha) descartarTrecho()
    return falha
  }

  const moverBordaDoTrecho = (borda: Borda, ms: number) =>
    setTrecho((t) => (t ? { ...t, [borda === 'inicio' ? 'inicio_ms' : 'fim_ms']: ms } : t))

  /** F2: a linha do item em foco vira o formulário dos campos do tipo. */
  function corrigirEmFoco() {
    // Com a correção aberta, o F2 e o Del (vindos de uma alça ou de um botão) não a descartam.
    if (emEdicao) return
    corrigirItem(itens.find((i) => i.chave === selecionada))
  }

  function corrigirItem(item: ItemDoPainel | undefined) {
    if (!catalogando || !decupagem || !catalogo) return
    setDescrevendo(false)
    if (!item || !editorDoItem(decupagem, item, catalogo)) {
      mostrarAviso('Selecione no painel um item que possa ser corrigido (↑ ↓).')
      return
    }
    setTemposDaAlca(null)
    selecionar(item.chave)
    setEmEdicao({ chave: item.chave, modo: 'editar' })
  }

  /** Del: "não é isto" no item em foco, com a confirmação na mesma linha. */
  function removerEmFoco() {
    if (emEdicao) return
    removerItem(itens.find((i) => i.chave === selecionada))
  }

  function removerItem(item: ItemDoPainel | undefined) {
    if (!catalogando || !decupagem) return
    if (!item || !podeRemover(decupagem, item)) {
      mostrarAviso('Não há "não é isto" para o item em foco.')
      return
    }
    setTemposDaAlca(null)
    selecionar(item.chave)
    setEmEdicao({ chave: item.chave, modo: 'remover' })
  }

  // O número do botão é o que a pessoa pode resolver: a fila e, para quem aprova, as pendentes.
  const aResolver = fila.length + (podeAprovar ? historico.filter((h) => h.estado === 'pendente').length : 0)

  /** Da gaveta ao painel: seleciona o item da correção, abre a aba dele e salta o player. */
  function saltarAoItemDaCorrecao(correcao: ItemDoHistorico): boolean {
    const item = decupagem ? itemDaCorrecao(decupagem, itens, correcao) : undefined
    if (!item) return false
    selecionar(item.chave)
    const aberta = abaDaChave(item.chave)
    if (aberta) setAba(aberta)
    saltarPara(item.inicio_ms / 1000)
    return true
  }

  function selecionar(chave: string | null) {
    if (chave !== selecionada) fecharEdicao()
    setSelecionada(chave)
  }

  /** N e Shift+N: o momento seguinte ou anterior do resultado, também entre vídeos. */
  function passarDeMomento(passo: 1 | -1) {
    if (!busca) return
    if (!resultadoDaBusca) {
      mostrarAviso(
        buscaFalhou
          ? `A busca não carregou. Volte à busca e abra o vídeo de novo (código ${buscaFalhou}).`
          : 'A busca ainda está carregando.',
      )
      return
    }
    const atual = (player.current?.currentTime ?? 0) * 1000
    const destino = passoNoResultado(resultadoDaBusca, job.id, atual, passo)
    if (!destino) {
      mostrarAviso(
        resultadoDaBusca.some((v) => v.job_id === job.id)
          ? `Este é o ${passo === 1 ? 'último' : 'primeiro'} momento da busca.`
          : 'Este vídeo não está no resultado da busca.',
      )
      return
    }
    if (destino.job_id === job.id) saltarPara(destino.inicio_ms / 1000)
    else navegar(enderecoDoVideo(destino.job_id, destino.inicio_ms / 1000, busca))
  }

  function fecharBusca() {
    navegar(enderecoDoVideo(job.id, player.current?.currentTime ?? t), { substituir: true })
  }

  function mostrarAviso(texto: string) {
    setAviso(texto)
    clearTimeout(avisoDoDesfazer.current)
    avisoDoDesfazer.current = setTimeout(() => setAviso(null), AVISO_DO_DESFAZER_MS)
  }

  const ultimaDoEditor = useCallback(async () => {
    const [eu, historico] = await Promise.all([api.eu(), api.job(job.id).historico()])
    return historico.find((c) => c.autor_email === eu.email && desfazivel(c))
  }, [api, job.id])

  // O botão "Desfazer" só fica ativo quando há correção do editor para desfazer.
  useEffect(() => {
    if (!catalogando) return
    let ativo = true
    ultimaDoEditor().then(
      (ultima) => {
        if (ativo) setTemParaDesfazer(Boolean(ultima))
      },
      () => {
        if (ativo) setTemParaDesfazer(false)
      },
    )
    return () => {
      ativo = false
    }
  }, [ultimaDoEditor, catalogando, cargasDaDecupagem])

  /** Ctrl+Z e o botão "Desfazer": desfaz a correção mais recente do próprio editor, com o motivo do gesto. */
  async function desfazerUltima() {
    if (!catalogando || !decupagem || desfazendo.current) return
    desfazendo.current = true
    try {
      const ultima = await ultimaDoEditor()
      if (!ultima) {
        mostrarAviso('Nada para desfazer neste vídeo.')
        return
      }
      await api.job(job.id).desfazer(ultima.id, 'correção desfeita pelo editor')
      setCargasDaDecupagem((n) => n + 1)
      const rotulo = catalogo ? rotuloDe(catalogo.tipos, ultima.tipo) : ultima.tipo
      mostrarAviso(`Desfeito: ${rotulo} (${ultima.depois_legivel} → ${ultima.antes_legivel})`)
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) mostrarAviso('Não foi possível desfazer a correção.')
    } finally {
      desfazendo.current = false
    }
  }

  const apontarObjeto = useCallback((o: ObjetoApontado | null) => {
    const { videoWidth, videoHeight } = player.current ?? { videoWidth: 0, videoHeight: 0 }
    setObjetoApontado(o && videoWidth && videoHeight ? { ...o, proporcao: videoWidth / videoHeight } : o)
  }, [])
  // As URLs assinadas dos quadros valem alguns minutos: o cache evita pedir de novo a cada linha.
  const urlDoQuadro = useMemo(() => criarCacheDeQuadros((arquivo) => api.job(job.id).quadro(arquivo)), [api, job.id])

  const faixas = useMemo(() => (decupagem ? faixasDoVisualizador(decupagem) : null), [decupagem])
  const duracaoDaLinhaMs = duracaoDaLinha(duracaoMs, faixas ?? [])

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
    setAtualMs(el.currentTime * 1000)
  }

  function mudarVelocidade(v: number) {
    if (player.current) player.current.playbackRate = v
    setVelocidade(v)
  }

  const fps = job.taxa_de_quadros ?? null
  const alternar = useCallback(() => {
    const el = player.current
    if (!el) return
    pararEm.current = null
    if (el.paused) tocar(el)
    else el.pause()
  }, [])
  const tocarMaisRapido = () => {
    const el = player.current
    if (!el) return
    // Pausado, o L recomeça o ciclo: toca em 1×.
    if (el.paused) {
      mudarVelocidade(1)
      tocar(el)
      return
    }
    const seguinte = VELOCIDADES.find((v) => v > el.playbackRate) ?? VELOCIDADES[VELOCIDADES.length - 1]
    mudarVelocidade(seguinte)
  }
  function reproduzirTrecho(trecho: { inicio_ms: number; fim_ms: number }) {
    const el = player.current
    if (!el) return
    saltarPara(trecho.inicio_ms / 1000)
    pararEm.current = trecho.fim_ms
    tocar(el)
  }
  function aoAtualizarOTempo(el: HTMLVideoElement) {
    setAtualMs(el.currentTime * 1000)
    // O `timeupdate` chega a cada ~250 ms: o player volta ao fim exato do trecho.
    if (pararEm.current !== null && el.currentTime * 1000 >= pararEm.current) {
      el.pause()
      el.currentTime = pararEm.current / 1000
      setAtualMs(pararEm.current)
      pararEm.current = null
    }
  }
  const telaCheia = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void moldura.current?.requestFullscreen?.()
  }

  const recuarOuAvancar = (passo: number) => ({
    casa: (e: KeyboardEvent) =>
      (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.shiftKey === (passo === SALTO_LONGO_S),
    executar: (e: KeyboardEvent) =>
      saltarPara((player.current?.currentTime ?? 0) + (e.key === 'ArrowLeft' ? -passo : passo)),
  })

  useAtalhos([
    {
      tecla: 'Espaço ou K',
      acao: 'Tocar e pausar',
      grupo: GRUPO,
      casa: (e) => tecla(e, ' ', 'k'),
      executar: alternar,
    },
    {
      tecla: 'L',
      acao: 'Tocar; de novo, 2×; de novo, 4×',
      grupo: GRUPO,
      casa: (e) => tecla(e, 'l'),
      executar: tocarMaisRapido,
    },
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
    {
      tecla: '← →',
      acao: 'Numa faixa: passar de ocorrência (o player não anda)',
      grupo: GRUPO_DA_LINHA,
    },
    { tecla: 'Enter', acao: 'Numa faixa: saltar à ocorrência', grupo: GRUPO_DA_LINHA },
    ...(busca
      ? [
          {
            tecla: 'N',
            acao: 'Ir ao momento seguinte da busca, também no vídeo seguinte do resultado',
            grupo: GRUPO_DA_BUSCA,
            // No modo de catalogação com sugestões abertas, o N é do "recusar".
            casa: (e: KeyboardEvent) => tecla(e, 'n') && !e.shiftKey && !(catalogando && sugestoes.length > 0),
            executar: () => passarDeMomento(1),
          },
          {
            tecla: 'Shift + N',
            acao: 'Ir ao momento anterior da busca, também no vídeo anterior do resultado',
            grupo: GRUPO_DA_BUSCA,
            casa: (e: KeyboardEvent) => tecla(e, 'n') && e.shiftKey,
            executar: () => passarDeMomento(-1),
          },
        ]
      : []),
    ...(podeEditar
      ? [
          {
            tecla: 'E',
            acao: 'Ligar e desligar o modo de catalogação',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'e'),
            executar: alternarCatalogacao,
          },
          {
            tecla: 'Ctrl + Z',
            acao: 'Desfazer a última correção sua neste vídeo',
            grupo: GRUPO_DA_CATALOGACAO,
            ctrl: true,
            // Ctrl+Shift+Z é o refazer de outros programas: aqui não desfaz.
            casa: (e: KeyboardEvent) => tecla(e, 'z') && !e.shiftKey,
            executar: () => void desfazerUltima(),
          },
          {
            tecla: 'I',
            acao: 'Marcar a entrada do trecho no tempo atual',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'i'),
            executar: marcarEntrada,
          },
          {
            tecla: 'O',
            acao: 'Marcar a saída do trecho no tempo atual',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'o'),
            executar: marcarSaida,
          },
          {
            tecla: 'A',
            acao: 'Descrever o trecho marcado',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => tecla(e, 'a'),
            executar: descreverTrecho,
          },
          ...ABAS_DO_TRECHO.map((a) => ({
            tecla: a.tecla,
            acao: `No campo do trecho: o tipo ${a.rotulo}`,
            grupo: GRUPO_DA_CATALOGACAO,
          })),
          {
            tecla: 'Shift + Enter',
            acao: 'Num campo de nome: criar o nome digitado no catálogo, a revisar',
            grupo: GRUPO_DA_CATALOGACAO,
          },
          {
            tecla: 'Esc',
            acao: 'Descartar o trecho marcado',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => e.key === 'Escape' && catalogando && !gavetaAberta && trecho !== null && !descrevendo,
            executar: (e: KeyboardEvent) => {
              e.preventDefault()
              descartarTrecho()
            },
          },
          {
            tecla: 'F2',
            acao: 'Corrigir o item em foco',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => e.key === 'F2',
            executar: corrigirEmFoco,
          },
          {
            tecla: 'Del',
            acao: 'Não é isto: remover a pessoa do item em foco',
            grupo: GRUPO_DA_CATALOGACAO,
            casa: (e: KeyboardEvent) => e.key === 'Delete',
            executar: removerEmFoco,
          },
        ]
      : []),
  ])

  // O formulário (ou a confirmação) que toma o lugar da linha em foco, e as alças dos tempos.
  const itemEmEdicao = emEdicao ? itens.find((i) => i.chave === emEdicao.chave) : undefined
  let edicaoNoPainel: EdicaoNoPainel | null = null
  let alcasDaCorrecao: AlcasDaCorrecao | null = null
  if (catalogando && decupagem && catalogo && emEdicao) {
    if (emEdicao.modo === 'acrescentar') {
      const pessoa = decupagem.pessoas.find((p) => `acrescentar:${p.id}` === emEdicao.chave)
      if (pessoa)
        edicaoNoPainel = {
          chave: emEdicao.chave,
          conteudo: (
            <FormularioDeCorrecao
              editor={editorDeNovaAparicao(pessoa, atualMs, catalogo)}
              rotulo={`Acrescentar aparição de ${pessoa.nome}`}
              limiteDoMotivo={catalogo.limites.motivo}
              aoSalvar={gravar}
              aoCancelar={fecharEdicao}
            />
          ),
        }
    } else if (itemEmEdicao && emEdicao.modo === 'editar') {
      const editor = editorDoItem(decupagem, itemEmEdicao, catalogo)
      if (editor) {
        edicaoNoPainel = {
          chave: emEdicao.chave,
          conteudo: (
            <FormularioDeCorrecao
              editor={editor}
              rotulo={`Corrigir ${itemEmEdicao.titulo}`}
              limiteDoMotivo={catalogo.limites.motivo}
              tempos={temposDaAlca}
              salvarRef={salvarDasAlcas}
              aoSalvar={gravar}
              aoCancelar={fecharEdicao}
            />
          ),
        }
        if (editor.intervalo) {
          const atual = temposDaAlca ?? editor.intervalo
          alcasDaCorrecao = {
            chave: emEdicao.chave,
            inicio_ms: atual.inicio_ms,
            fim_ms: atual.fim_ms,
            aoSalvar: () => salvarDasAlcas.current?.(),
            aoDescartar: fecharEdicao,
            aoMover: (borda: Borda, ms: number) =>
              setTemposDaAlca({ ...atual, [borda === 'inicio' ? 'inicio_ms' : 'fim_ms']: ms }),
          }
        }
      }
    } else if (itemEmEdicao && emEdicao.modo === 'remover') {
      const pedido = pedidoDeRemocao(decupagem, itemEmEdicao)
      if (pedido) {
        const alvo = itemEmEdicao.tipo === 'mencao' ? 'desta menção' : 'desta aparição'
        edicaoNoPainel = {
          chave: emEdicao.chave,
          conteudo: (
            <ConfirmacaoDeRemocao
              texto={`Remover ${itemEmEdicao.titulo} ${alvo}?`}
              aoConfirmar={async () => {
                const falha = await gravar([pedido], motivoDaRemocao(pedido))
                if (falha) mostrarAviso(falha)
              }}
              aoCancelar={fecharEdicao}
            />
          ),
        }
      }
    }
  }

  // A identidade do intervalo só muda quando uma borda anda: o formulário acompanha as alças.
  const trechoDoFormulario = useMemo(
    () => ({ inicio_ms: trecho?.inicio_ms ?? 0, fim_ms: trecho?.fim_ms ?? 0 }),
    [trecho?.inicio_ms, trecho?.fim_ms],
  )
  const trechoNaLinha: TrechoMarcado | null =
    catalogando && trecho
      ? {
          ...trecho,
          aoMover: moverBordaDoTrecho,
          aoSalvar: () => salvarDoTrecho.current?.(),
          aoDescartar: descartarTrecho,
        }
      : null

  function acrescentarAparicao(pessoa: string) {
    setTemposDaAlca(null)
    setEmEdicao({ chave: `acrescentar:${pessoa}`, modo: 'acrescentar' })
  }

  const tc = useMemo(
    () =>
      job.timecode_origem && fps
        ? timecodeNoInstante(job.timecode_origem, fps, atualMs)
        : null,
    [job.timecode_origem, fps, atualMs],
  )

  async function copiarTc() {
    if (!tc) return
    try {
      await navigator.clipboard.writeText(tc)
    } catch {
      return
    }
    setCopiado(true)
    clearTimeout(avisoDoTc.current)
    avisoDoTc.current = setTimeout(() => setCopiado(false), AVISO_DO_TC_MS)
  }

  async function baixar() {
    setFalhaDoJson(null)
    try {
      baixarDecupagem(job.nome, await api.job(job.id).decupagem())
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) setFalhaDoJson(codigoDoErro(e))
    }
  }

  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e continua
  // do mesmo ponto. Com o link ainda válido, a falha é do arquivo, e pedir de novo não adianta.
  function aoFalharOPlayer() {
    if (!reproducao) return
    retomarEm.current = player.current?.currentTime ?? null
    if (Date.parse(reproducao.expira_em) > Date.now()) setErro(`midia_${player.current?.error?.code ?? 0}`)
    else setTentativas((n) => n + 1)
  }

  const titulo = [job.programa, job.data_exibicao ? dataDeExibicao(job.data_exibicao) : null].filter(Boolean)

  return (
    <NomesDoCatalogo.Provider value={api.nomes}>
    <Stack
      gap="xs"
      h={`calc(100vh - ${ALTURA_DA_BARRA}px - 2 * var(--mantine-spacing-sm))`}
      style={{ overflow: 'hidden' }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          {titulo.length > 0 && <Text fw={700}>{titulo.join(' · ')}</Text>}
          <Text size="sm" c="dimmed" truncate>
            {titulo.length > 0 ? `· ${job.nome}` : job.nome}
          </Text>
          {decupagem && (
            <Tooltip
              label={
                decupagem.manifesto_do_pipeline
                  ? JSON.stringify(decupagem.manifesto_do_pipeline, null, 1)
                  : 'Decupagem feita antes da versão fixa do pipeline'
              }
              multiline
              maw={420}
              events={{ hover: true, focus: true, touch: true }}
            >
              <Text size="xs" c="dimmed" tabIndex={0} style={{ whiteSpace: 'nowrap' }}>
                Pipeline {decupagem.versao_pipeline ?? 'anterior à versão'}
              </Text>
            </Tooltip>
          )}
        </Group>
        <Group gap="xs" wrap="nowrap">
          {passadas.length > 0 && (
            <SeletorDePassada passadas={passadas} valor={comparandoCom} aoEscolher={setComparandoCom} />
          )}
          {podeEditar && (
            <Tooltip label="Histórico, fila de revisão e aprovação">
              <Indicator
                disabled={aResolver === 0}
                label={aResolver}
                size={16}
                color={CORES.andamento}
              >
                <ActionIcon
                  variant={gavetaAberta ? 'filled' : 'default'}
                  aria-label="Histórico"
                  aria-pressed={gavetaAberta}
                  onClick={() => setGavetaAberta((a) => !a)}
                >
                  <IconHistory />
                </ActionIcon>
              </Indicator>
            </Tooltip>
          )}
          {podeReprocessar && job.estado === 'concluido' && !job.etapa_atual && !acompanhando && !escolhendo && (
            <Button
              variant="default"
              leftSection={<IconRefresh />}
              onClick={() => setEscolhendo(true)}
            >
              Reprocessar…
            </Button>
          )}
          {job.estado === 'concluido' && (
            <Tooltip label="Baixar decupagem (JSON)">
              <ActionIcon variant="default" aria-label="Baixar decupagem (JSON)" onClick={() => void baixar()}>
                <IconDownload />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Group>
      {escolhendo && (
        <ReprocessarEtapa
          api={api.job(job.id)}
          aoReprocessar={aoReprocessar}
          aoCancelar={() => setEscolhendo(false)}
        />
      )}
      {job.etapa_atual && (
        <Text size="sm" c={CORES.andamento} role="status">
          {`${acompanhando ? 'Reprocessando: ' : ''}${nomeDaEtapa(job.etapa_atual)} em andamento.`}
          {acompanhando && job.estado === 'analisando' && ' A Decupagem está sendo refeita e volta quando a análise terminar.'}
        </Text>
      )}
      {falhaDoJson && (
        <AlertaDeErro
          mensagem="Não foi possível baixar a decupagem. Tente de novo em instantes."
          codigo={falhaDoJson}
          aoTentar={() => void baixar()}
        />
      )}
      <Group gap="sm" align="stretch" wrap="nowrap" style={{ flex: 1, minHeight: 0 }}>
        <Stack gap="xs" style={{ flex: '1 1 0', minWidth: 0, minHeight: 0 }}>
          {erro ? (
            <AlertaDeErro
              mensagem="Não foi possível carregar o vídeo. Tente de novo em instantes."
              codigo={erro}
              aoTentar={() => {
                setErro(null)
                setTentativas((n) => n + 1)
              }}
            />
          ) : (
            <Box
              ref={moldura}
              style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
              bg="dark.7"
            >
              <Box style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex' }}>
              <video
                ref={player}
                src={reproducao?.url}
                aria-label="Player"
                onClick={alternar}
                onError={aoFalharOPlayer}
                onLoadedMetadata={(e) => {
                  const el = e.currentTarget
                  if (Number.isFinite(el.duration)) setDuracaoMs(el.duration * 1000)
                  if (retomarEm.current !== null) {
                    el.currentTime = retomarEm.current
                    setAtualMs(el.currentTime * 1000)
                    retomarEm.current = null
                  }
                }}
                onTimeUpdate={(e) => aoAtualizarOTempo(e.currentTarget)}
                onPlay={() => setTocando(true)}
                onPause={() => {
                  setTocando(false)
                  gravarNoEndereco()
                }}
                onSeeked={gravarNoEndereco}
                onRateChange={(e) => setVelocidade(e.currentTarget.playbackRate)}
                style={{ flex: 1, minHeight: 0, width: '100%', objectFit: 'contain', background: 'var(--mantine-color-black)' }}
              />
              {objetoApontado && (
                <QuadroDoObjeto
                  objeto={objetoApontado}
                  urlDoQuadro={urlDoQuadro}
                />
              )}
              </Box>
              <Paper withBorder p="xs">
                <Group gap="sm" wrap="nowrap">
                  <Tooltip label={tocando ? 'Pausar (Espaço)' : 'Tocar (Espaço)'}>
                    <ActionIcon
                      variant="default"
                      aria-label={tocando ? 'Pausar' : 'Tocar'}
                      onClick={alternar}
                    >
                      {tocando ? <IconPlayerPause /> : <IconPlayerPlay />}
                    </ActionIcon>
                  </Tooltip>
                  <Button.Group aria-label="Velocidade">
                    {VELOCIDADES.map((v) => (
                      <Button
                        key={v}
                        size="compact-sm"
                        variant={velocidade === v ? 'filled' : 'default'}
                        aria-pressed={velocidade === v}
                        onClick={() => mudarVelocidade(v)}
                      >
                        {`${v}×`}
                      </Button>
                    ))}
                  </Button.Group>
                  <Text style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {`${relogio(atualMs)} / ${relogio(duracaoMs)}`}
                  </Text>
                  {tc && (
                    <Tooltip label="Copiar o timecode">
                      <Text
                        component="button"
                        type="button"
                        ff="monospace"
                        size="sm"
                        c="dimmed"
                        aria-label={`Copiar o timecode ${tc}`}
                        onClick={() => void copiarTc()}
                        style={{ background: 'none', border: 0, cursor: 'pointer', fontVariantNumeric: 'tabular-nums' }}
                      >
                        {`TC ${tc}`}
                      </Text>
                    </Tooltip>
                  )}
                  <Text size="xs" c="dimmed" role="status">
                    {copiado ? 'Timecode copiado' : ''}
                  </Text>
                  <Box style={{ flex: 1 }} />
                  {catalogando && (
                    <Group gap={4} wrap="nowrap" aria-label="Trecho">
                      <Tooltip label="Marcar entrada (I)">
                        <Button size="compact-sm" variant="default" onClick={marcarEntrada}>
                          Marcar entrada
                        </Button>
                      </Tooltip>
                      <Tooltip label="Marcar saída (O)">
                        <Button size="compact-sm" variant="default" onClick={marcarSaida}>
                          Marcar saída
                        </Button>
                      </Tooltip>
                      {trecho?.fim_ms != null && (
                        <>
                          <Tooltip label="Descrever o trecho (A)">
                            <Button size="compact-sm" onClick={descreverTrecho}>
                              Descrever o trecho
                            </Button>
                          </Tooltip>
                          <Tooltip label="Descartar o trecho (Esc)">
                            <ActionIcon variant="default" aria-label="Descartar o trecho" onClick={descartarTrecho}>
                              <IconX size={16} />
                            </ActionIcon>
                          </Tooltip>
                        </>
                      )}
                    </Group>
                  )}
                  <Tooltip label={mudo ? 'Ligar o som' : 'Silenciar'}>
                    <ActionIcon
                      variant="default"
                      aria-label={mudo ? 'Ligar o som' : 'Silenciar'}
                      onClick={() => {
                        if (player.current) player.current.muted = !mudo
                        setMudo(!mudo)
                      }}
                    >
                      {mudo ? <IconVolumeOff /> : <IconVolume />}
                    </ActionIcon>
                  </Tooltip>
                  <Slider
                    w={90}
                    min={0}
                    max={1}
                    step={0.05}
                    size="xs"
                    value={volume}
                    label={null}
                    aria-label="Volume"
                    onChange={(v) => {
                      if (player.current) player.current.volume = v
                      setVolume(v)
                    }}
                  />
                  <Tooltip label="Tela cheia (F)">
                    <ActionIcon variant="default" aria-label="Tela cheia" onClick={telaCheia}>
                      <IconMaximize />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              </Paper>
            </Box>
          )}
          {falhaDaDecupagem && (
            <AlertaDeErro
              mensagem="Não foi possível carregar a linha do tempo. Tente de novo em instantes."
              codigo={falhaDaDecupagem}
              aoTentar={() => {
                setFalhaDaDecupagem(null)
                setCargasDaDecupagem((n) => n + 1)
              }}
            />
          )}
          {faixas && (
            <FaixasDoVideo
              faixas={faixas}
              cortesMs={job.cortes_ms}
              duracaoMs={duracaoDaLinhaMs}
              atualMs={atualMs}
              selecionada={selecionada}
              aoSaltar={(ms) => saltarPara(ms / 1000)}
              alcas={alcasDaCorrecao}
              trecho={trechoNaLinha}
              busca={
                busca && momentosDaBusca.length > 0
                  ? {
                      rotulo: rotuloDaBusca(busca, momentosDaBusca.length),
                      momentos: momentosDaBusca,
                      atual: momentoAtual(momentosDaBusca, atualMs),
                      aoSaltar: (ms) => saltarPara(ms / 1000),
                      aoFechar: fecharBusca,
                    }
                  : null
              }
              aoSelecionar={(chave, inicioMs) => {
                selecionar(chave)
                const aberta = abaDaChave(chave)
                if (aberta) setAba(aberta)
                saltarPara(inicioMs / 1000)
              }}
            />
          )}
        </Stack>
        <Paper
          withBorder
          p="sm"
          aria-label="Painel"
          style={{
            flex: comparandoCom ? '0 0 62%' : '0 0 38%',
            minWidth: 380,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {comparandoCom && (
            <ComparacaoDePassada
              api={clienteDoJob}
              passadaId={comparandoCom}
              aoSaltar={(ms) => saltarPara(ms / 1000)}
            />
          )}
          {!comparandoCom && (
            <>
          {podeEditar && (
            <Group gap="xs" mb="xs" wrap="nowrap">
              <Tooltip label="Catalogar (E)">
                <Button
                  size="compact-sm"
                  variant={catalogando ? 'filled' : 'default'}
                  aria-pressed={catalogando}
                  onClick={alternarCatalogacao}
                >
                  Catalogar
                </Button>
              </Tooltip>
              {catalogando && (
                <>
                  <Text size="sm" fw={600}>
                    Catalogando
                  </Text>
                  <Kbd size="xs">E</Kbd>
                  <Tooltip label="Desfazer a última correção (Ctrl+Z)">
                    <ActionIcon
                      variant="default"
                      aria-label="Desfazer"
                      disabled={!temParaDesfazer}
                      onClick={() => void desfazerUltima()}
                    >
                      <IconArrowBackUp size={16} />
                    </ActionIcon>
                  </Tooltip>
                </>
              )}
            </Group>
          )}
          {aviso && (
            <Text size="sm" role="status" mb="xs">
              {aviso}
            </Text>
          )}
          {catalogando && catalogo && descrevendo && trecho?.fim_ms != null && (
            <FormularioDoTrecho
              trecho={trechoDoFormulario}
              catalogo={catalogo}
              salvarRef={salvarDoTrecho}
              aoSalvar={gravarTrecho}
              aoCancelar={() => setDescrevendo(false)}
            />
          )}
          {podeEditar && (
            <Sugestoes
              sugestoes={catalogando ? sugestoes : []}
              decupagem={decupagem}
              api={api.job(job.id)}
              ativo={catalogando}
              aoSaltar={(ms) => saltarPara(ms / 1000)}
              aoResolver={(id) => {
                setSugestoes((lista) => lista.filter((x) => x.id !== id))
                setCargasDaDecupagem((n) => n + 1)
              }}
              aoFalhar={() => setCargasDeSugestoes((n) => n + 1)}
              aoAvisar={mostrarAviso}
            />
          )}
          {decupagem ? (
            <Painel
              decupagem={decupagem}
              duracaoMs={duracaoDaLinhaMs}
              atualMs={atualMs}
              aba={aba}
              aoTrocarAba={setAba}
              selecionada={selecionada}
              pessoasAbertas={pessoasAbertas}
              aoAbrirPessoa={(id) =>
                setPessoasAbertas((abertas) => {
                  const novas = new Set(abertas)
                  if (!novas.delete(id)) novas.add(id)
                  return novas
                })
              }
              aoSelecionar={selecionar}
              edicao={edicaoNoPainel}
              marcas={marcas}
              aoAcrescentar={catalogando && catalogo ? acrescentarAparicao : undefined}
              acoes={
                catalogando && catalogo && decupagem
                  ? {
                      corrigir: corrigirItem,
                      remover: removerItem,
                      podeCorrigir: (i) => !!editorDoItem(decupagem, i, catalogo),
                      podeRemover: (i) => podeRemover(decupagem, i),
                    }
                  : undefined
              }
              aoSaltar={(ms) => saltarPara(ms / 1000)}
              aoReproduzir={reproduzirTrecho}
              urlDoQuadro={urlDoQuadro}
              aoApontarObjeto={apontarObjeto}
              atalhosAtivos={!gavetaAberta}
              fotosDoNome={fotosDoNome}
            />
          ) : (
            <Text size="sm" c="dimmed">
              {concluido ? 'Carregando a decupagem…' : 'O painel aparece quando a decupagem estiver pronta.'}
            </Text>
          )}
            </>
          )}
        </Paper>
      </Group>
      {podeEditar && (
        <Gaveta
          aberta={gavetaAberta}
          aba={abaDaGaveta}
          aoTrocarAba={setAbaDaGaveta}
          aoFechar={() => setGavetaAberta(false)}
          historico={historico}
          fila={fila}
          podeAprovar={podeAprovar}
          api={api.job(job.id)}
          catalogo={catalogo}
          falhaAoCarregar={falhaNoHistorico}
          aoMudar={() => setCargasDaDecupagem((n) => n + 1)}
          aoSaltar={saltarAoItemDaCorrecao}
        />
      )}
    </Stack>
    </NomesDoCatalogo.Provider>
  )
}
