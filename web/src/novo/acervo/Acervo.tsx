import {
  IconBroadcast,
  IconChevronDown,
  IconCircleDot,
  IconFilterOff,
  IconLayoutGrid,
  IconList,
  IconPhoto,
  IconPhotoScan,
  IconSortDescending,
  IconX,
} from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useState, type ReactNode } from 'react'
import { SessaoExpirada } from '../../api.ts'
import { useAtalhos, type Atalho } from '../../atalhos.ts'
import { baixarDecupagem } from '../../baixar.ts'
import { ESTADOS_DO_JOB } from '../../cores.ts'
import { nomeDaEtapa } from '../../etapas.ts'
import { falhaDaAcao, type Falha as FalhaDaAcao } from '../../falhaDaAcao.ts'
import { filtrosParaBusca, haFiltro, SEM_FILTROS, type FiltrosDoAcervo, type Job, type Ordem } from '../../jobs.ts'
import { ACERVO, enderecoDoVideo, navegar } from '../../rotas.ts'
import { Falha } from '../comum/Falha.tsx'
import { GradeVirtual } from '../comum/GradeVirtual.tsx'
import { MandarParaLixeira } from '../comum/MandarParaLixeira.tsx'
import { Reprocessar } from '../comum/Reprocessar.tsx'
import { useApi, useProgramas } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '../ui/dropdown-menu.tsx'
import { Slider } from '../ui/slider.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { BuscaPorNome, Faceta, Periodo } from './Filtros.tsx'
import { tirarDoAcervo, trocarNoAcervo, useAcervo, useAndamento } from './useAcervo.ts'
import { Cartao, Esqueleto, Linha, type Acao } from './Video.tsx'

/** A largura mínima do cartão em cada passo do controle de tamanho. */
const TAMANHOS = [200, 260, 320, 420]
/** A altura do cartão abaixo da imagem (texto e selo) e a da linha da lista, para a estimativa antes de medir. */
const TEXTO_DO_CARTAO = 90
const ALTURA_DA_LINHA = 80
const ORDENS: Record<Ordem, string> = { enviado: 'Data de envio', exibicao: 'Data de exibição' }
const ESTADOS = Object.entries(ESTADOS_DO_JOB).map(([valor, e]) => ({ valor, rotulo: e.rotulo }))

const ATALHOS: Atalho[] = [
  { tecla: '← → ↑ ↓', acao: 'No acervo: ir ao vídeo ao lado', grupo: 'Acervo' },
  { tecla: 'Enter', acao: 'No acervo: abrir o vídeo', grupo: 'Acervo' },
]

// A exibição e o tamanho ficam no navegador: voltar do vídeo reabre do mesmo jeito.
const EXIBICAO = 'mam:acervo:exibicao'
const TAMANHO = 'mam:acervo:tamanho'
// Sem armazenamento (modo privado, bloqueado, cota), vale o padrão e a escolha dura só a visita.
function ler(chave: string) {
  try {
    return localStorage.getItem(chave)
  } catch {
    return null
  }
}
function guardar(chave: string, valor: string) {
  try {
    localStorage.setItem(chave, valor)
  } catch {
    // fica só na memória
  }
}
function lerTamanho() {
  const n = Number(ler(TAMANHO) ?? 1)
  return Number.isInteger(n) && n >= 0 && n < TAMANHOS.length ? n : 1
}

function irPara(filtros: FiltrosDoAcervo, opcoes: { substituir?: boolean } = {}) {
  navegar(`${ACERVO}${filtrosParaBusca(filtros)}`, opcoes)
}

function BotaoDeIcone({ rotulo, ativo, onClick, children }: { rotulo: string; ativo: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={rotulo}
          aria-pressed={ativo}
          onClick={onClick}
          className={cn('flex size-6 items-center justify-center rounded-xs text-muted-foreground hover:bg-accent hover:text-foreground', ativo && 'bg-selected text-link')}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{rotulo}</TooltipContent>
    </Tooltip>
  )
}

/**
 * O acervo da opção B (Galeria): grade de cartões ou lista, com os filtros na URL. A grade é
 * virtual (só as fileiras à vista e 3 de folga existem na página) e paginada (6 páginas de 50
 * na memória, nos dois sentidos). Voltar do vídeo volta ao mesmo vídeo.
 */
export function Acervo({ filtros, permissoes = [], intervaloMs = 15_000 }: { filtros: FiltrosDoAcervo; permissoes?: readonly string[]; intervaloMs?: number }) {
  const api = useApi()
  const cliente = useQueryClient()
  const acervo = useAcervo(filtros)
  const falhaDoAndamento = useAndamento(filtros, acervo.itens, intervaloMs)
  const programas = useProgramas()
  const [lista, setLista] = useState(() => ler(EXIBICAO) === 'lista')
  const [tamanho, setTamanho] = useState(lerTamanho)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<FalhaDaAcao | null>(null)
  const [paraLixeira, setParaLixeira] = useState<Job | null>(null)
  const [paraReprocessar, setParaReprocessar] = useState<Job | null>(null)
  useAtalhos(ATALHOS)

  const mudar = (parte: Partial<FiltrosDoAcervo>) => irPara({ ...filtros, ...parte })
  const limpar = () => irPara(SEM_FILTROS)
  const exibirEmLista = (v: boolean) => {
    setLista(v)
    guardar(EXIBICAO, v ? 'lista' : 'grade')
  }
  const mudarTamanho = (v: number) => {
    setTamanho(v)
    guardar(TAMANHO, String(v))
  }

  async function aoAcao(acao: Acao, job: Job) {
    setFalha(null)
    if (acao === 'lixeira') return setParaLixeira(job)
    if (acao === 'reprocessar') return setParaReprocessar(job)
    try {
      if (acao === 'copiar') {
        await navigator.clipboard.writeText(new URL(enderecoDoVideo(job.id), location.origin).href)
        setAviso(`Link de ${job.nome} copiado.`)
      } else {
        baixarDecupagem(job.nome, await api.job(job.id).baixarDecupagem())
      }
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) {
        setFalha(falhaDaAcao(erro, acao === 'copiar' ? 'Não foi possível copiar o link.' : 'Não foi possível baixar a decupagem. Tente de novo.'))
      }
    }
  }

  const comFiltro = haFiltro(filtros)
  const vazio = !acervo.carregando && !acervo.erro && acervo.quantidade === 0
  return (
    <GradeVirtual
      chave={acervo.chave}
      voltaInicial={acervo.voltaInicial}
      chegouNaVolta={acervo.chegouNaVolta}
      recomecos={acervo.recomecos}
      quantidade={acervo.quantidade}
      aoVer={acervo.aoVer}
      largura={TAMANHOS[tamanho]}
      lista={lista}
      alturaDoTexto={TEXTO_DO_CARTAO}
      alturaDaLinha={ALTURA_DA_LINHA}
      desenhar={(i) => {
        const job = acervo.item(i)
        if (!job) return <Esqueleto key={`e${i}`} lista={lista} />
        const Video = lista ? Linha : Cartao
        return <Video key={job.id} job={job} indice={i} permissoes={permissoes} aoAcao={(a, j) => void aoAcao(a, j)} />
      }}
      esqueleto={<Esqueleto lista={lista} />}
      carregando={acervo.carregando ? 'Carregando o acervo' : null}
      cabecalho={
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-xl font-semibold">Acervo</h1>
            <BuscaPorNome filtros={filtros} aoBuscar={(q) => irPara({ ...filtros, q }, { substituir: true })} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Faceta
              rotulo="Programa"
              Icone={IconBroadcast}
              unico
              opcoes={programas.map((p) => ({ valor: p, rotulo: p }))}
              valor={filtros.programa ? [filtros.programa] : []}
              aoMudar={([p]) => mudar({ programa: p ?? '' })}
            />
            <Faceta rotulo="Estado" Icone={IconCircleDot} opcoes={ESTADOS} valor={filtros.estado} aoMudar={(estado) => mudar({ estado })} />
            <Periodo de={filtros.de} ate={filtros.ate} aoMudar={mudar} />
            {comFiltro && (
              <Button type="button" variant="ghost" size="sm" onClick={limpar} className="text-link">
                <IconX stroke={1.75} aria-hidden /> Limpar filtros
              </Button>
            )}
            <div className="ml-auto flex items-center gap-2">
              {!lista && (
                <div className="hidden w-40 items-center gap-2 md:flex">
                  <IconPhoto size={14} className="shrink-0 text-muted-foreground" aria-hidden />
                  <Slider min={0} max={TAMANHOS.length - 1} step={1} value={[tamanho]} onValueChange={([v]) => mudarTamanho(v)} aria-label="Tamanho dos cartões" />
                  <IconPhotoScan size={18} className="shrink-0 text-muted-foreground" aria-hidden />
                </div>
              )}
              <div role="group" aria-label="Exibir como" className="flex h-7 items-center rounded-sm border border-strong p-0.5">
                <BotaoDeIcone rotulo="Grade" ativo={!lista} onClick={() => exibirEmLista(false)}>
                  <IconLayoutGrid size={16} stroke={1.75} aria-hidden />
                </BotaoDeIcone>
                <BotaoDeIcone rotulo="Lista" ativo={lista} onClick={() => exibirEmLista(true)}>
                  <IconList size={16} stroke={1.75} aria-hidden />
                </BotaoDeIcone>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button type="button" aria-label={`Ordenar por ${ORDENS[filtros.ordem].toLowerCase()}`} className="flex h-7 items-center gap-1 rounded-sm border border-strong bg-input px-2 text-sm">
                    <IconSortDescending size={16} stroke={1.75} className="text-muted-foreground" aria-hidden />
                    <span className="hidden sm:inline">{ORDENS[filtros.ordem]}</span>
                    <IconChevronDown size={14} className="opacity-60" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuRadioGroup value={filtros.ordem} onValueChange={(v) => mudar({ ordem: v as Ordem })}>
                    {Object.entries(ORDENS).map(([valor, rotulo]) => (
                      <DropdownMenuRadioItem key={valor} value={valor}>
                        {rotulo}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </>
      }
      avisos={
        (aviso || falha || acervo.erroAoPaginar || falhaDoAndamento) && (
          <div className="grid gap-2 px-3 pt-3 md:px-4">
            {aviso && (
              <p role="status" className="flex items-center gap-2 rounded-sm border border-ok/40 bg-ok/12 px-3 py-1 text-ok">
                <span className="min-w-0 flex-1">{aviso}</span>
                <button type="button" aria-label="Fechar o aviso" onClick={() => setAviso(null)} className="flex size-6 shrink-0 items-center justify-center rounded-xs hover:bg-accent">
                  <IconX size={14} aria-hidden />
                </button>
              </p>
            )}
            {falha && <Falha mensagem={falha.mensagem} codigo={falha.codigo} />}
            {acervo.erroAoPaginar ? (
              <Falha mensagem="Não foi possível carregar mais vídeos." codigo={acervo.erroAoPaginar} aoTentar={acervo.tentarDeNovo} />
            ) : (
              falhaDoAndamento && <Falha mensagem="Não foi possível atualizar a lista; tentando de novo." codigo={falhaDoAndamento} />
            )}
          </div>
        )
      }
    >
      {acervo.erro && (
        <div className="p-8">
          <Falha mensagem="Não foi possível carregar o acervo." codigo={acervo.erro} aoTentar={acervo.tentarDeNovo} className="mx-auto max-w-xl" />
        </div>
      )}
      {vazio && (
        <div className="grid justify-items-center gap-2 p-8 text-center text-muted-foreground">
          {comFiltro ? (
            <>
              <p>Nenhum vídeo com esses filtros.</p>
              <Button type="button" variant="secondary" size="sm" onClick={limpar}>
                <IconFilterOff stroke={1.75} aria-hidden /> Limpar filtros
              </Button>
            </>
          ) : (
            <p>Nenhum vídeo enviado ainda.</p>
          )}
        </div>
      )}

      {/* Os diálogos ficam fora da grade virtual: o cartão que sai da faixa à vista desmonta, e o diálogo iria junto. */}
      <MandarParaLixeira
        video={paraLixeira}
        aoFechar={() => setParaLixeira(null)}
        aoMandar={(v) => {
          setParaLixeira(null)
          setAviso(`${v.nome} foi para a lixeira.`)
          tirarDoAcervo(cliente, new Set([v.id]))
        }}
      />
      <Reprocessar
        video={paraReprocessar}
        aoFechar={() => setParaReprocessar(null)}
        aoReprocessar={(novo, etapa) => {
          setParaReprocessar(null)
          setAviso(`${novo.nome}: reprocessando a partir da etapa ${nomeDaEtapa(etapa)}.`)
          trocarNoAcervo(cliente, novo)
        }}
      />
    </GradeVirtual>
  )
}
