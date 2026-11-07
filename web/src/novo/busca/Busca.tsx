import {
  IconBroadcast,
  IconCalendarEvent,
  IconCategory,
  IconCheck,
  IconChevronDown,
  IconPhotoSearch,
  IconSearch,
  IconSortDescending,
  IconTag,
  IconUser,
  IconX,
} from '@tabler/icons-react'
import { cn } from 'cn'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { FalhaNaApi, PedidoInvalido, SessaoExpirada } from '../../api.ts'
import { useAtalhos } from '../../atalhos.ts'
import {
  consultaNova,
  contagemDeMencoes,
  contagemDeMomentos,
  contagemDeVideos,
  EVIDENCIAS,
  TAMANHO_DA_CONSULTA,
  type ConsultaDaBusca,
  type Evidencia,
  type NomeDaFaceta,
  type OrdemDaBusca,
  type TipoDeMomento,
  type ValorDaFaceta,
} from '../../busca.ts'
import { dataDeExibicao } from '../../jobs.ts'
import { guardado, guardarResultado } from '../../resultadoDaBusca.ts'
import { enderecoDaBusca, navegar } from '../../rotas.ts'
import { Falha } from '../comum/Falha.tsx'
import { GradeVirtual } from '../comum/GradeVirtual.tsx'
import { useProgramas } from '../consultas.ts'
import { Faceta } from '../acervo/Filtros.tsx'
import { Button } from '../ui/button.tsx'
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '../ui/dropdown-menu.tsx'
import { Cena, EsqueletoDaCena, TEXTO_DA_CENA } from './Cena.tsx'
import { useBusca, useEntrandoNaBusca, type PedidoDaBusca } from './useBusca.ts'

/** A largura mínima da cena na grade. */
const LARGURA_DA_CENA = 240
const ENTENDIDO = 'entendido'
const ANOS = Array.from({ length: 26 }, (_, i) => String(new Date().getFullYear() - i))
const ORDENS: Record<OrdemDaBusca, string> = { relevancia: 'Relevância', data: 'Data de exibição' }
const COR_DO_CHIP: Record<(typeof EVIDENCIAS)[number]['tipo'], string> = {
  aparicao: 'border-tipo-aparicao text-tipo-aparicao',
  mencao: 'border-tipo-mencao text-tipo-mencao',
  fala: 'border-tipo-fala text-tipo-fala',
  texto_na_tela: 'border-tipo-texto text-tipo-texto',
  objeto: 'border-tipo-objeto text-tipo-objeto',
  comercial: 'border-tipo-marca text-tipo-marca',
}
const FACETAS: { nome: Exclude<NomeDaFaceta, 'programa'>; rotulo: string; Icone: typeof IconUser }[] = [
  { nome: 'mes', rotulo: 'Data de exibição', Icone: IconCalendarEvent },
  { nome: 'pessoa', rotulo: 'Pessoa', Icone: IconUser },
  { nome: 'marca', rotulo: 'Marca', Icone: IconTag },
  { nome: 'tipo', rotulo: 'Tipo de momento', Icone: IconCategory },
]

type Tipo = PedidoDaBusca['tipo']
const CARREGANDO: Record<Tipo, string> = { texto: 'Buscando', imagem: 'Buscando pela imagem' }

function mensagemDoErro(tipo: Tipo, erro: unknown): string {
  // Na foto, a API explica o tipo e o tamanho errados em português.
  if (tipo === 'imagem' && erro instanceof PedidoInvalido) return erro.message
  const status = erro instanceof FalhaNaApi ? erro.status : 0
  if (status === 429) return 'Muitas buscas seguidas. Espere alguns segundos.'
  if (tipo === 'imagem' && status === 503) return 'A busca por imagem não está disponível agora.'
  if (status === 504) return tipo === 'texto' ? 'A busca demorou demais. Tente uma consulta mais específica.' : 'A busca demorou demais. Tente de novo.'
  return 'Não foi possível buscar agora. Tente de novo.'
}

/** "01/03/2020 a 31/12/2024", "Desde 01/03/2020", "Até 31/12/2024". */
function rotuloDoPeriodo(desde: string | null, ate: string | null): string {
  if (desde && ate) return `${dataDeExibicao(desde)} a ${dataDeExibicao(ate)}`
  return desde ? `Desde ${dataDeExibicao(desde)}` : `Até ${dataDeExibicao(ate)}`
}

const opcoesDa = (valores: ValorDaFaceta[]) => valores.map((v) => ({ valor: v.valor, rotulo: v.rotulo, contagem: v.videos }))

function Alternar({ ligado, desabilitado, cor, aoAlternar, children }: { ligado: boolean; desabilitado?: boolean; cor: string; aoAlternar: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={ligado}
      disabled={desabilitado}
      onClick={aoAlternar}
      className={cn(
        'flex h-7 items-center gap-1 rounded-sm border px-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-70',
        ligado ? cn('bg-selected', cor) : 'border-strong bg-input text-muted-foreground hover:text-foreground',
      )}
    >
      {ligado && <IconCheck size={14} aria-hidden />}
      {children}
    </button>
  )
}

/**
 * A grade de cenas de uma busca (texto ou foto), paginada por cursor, com o aviso dos
 * vídeos que ainda estão entrando no índice (#404). O cabeçalho e os avisos próprios vêm de quem chama.
 */
function GradeDaBusca({
  pedido,
  termo,
  cabecalho,
  avisos,
  semPedido,
  vazio,
  contagem,
}: {
  pedido: PedidoDaBusca | null
  /** O termo que o vídeo aberto daqui percorre com N e Shift+N, ou ''. */
  termo: string
  cabecalho: (busca: ReturnType<typeof useBusca>) => ReactNode
  avisos?: (busca: ReturnType<typeof useBusca>) => ReactNode
  semPedido?: ReactNode
  vazio: (busca: ReturnType<typeof useBusca>) => ReactNode
  contagem: (busca: ReturnType<typeof useBusca>) => string
}) {
  const busca = useBusca(pedido)
  const entrando = useEntrandoNaBusca(pedido !== null)
  const tipo = pedido?.tipo ?? 'texto'

  // O vídeo aberto daqui percorre este resultado com N e Shift+N.
  useEffect(() => {
    if (pedido?.tipo === 'texto' && busca.paginas && !busca.atualizando) guardarResultado(termo, guardado(busca.paginas.flatMap((p) => p.videos)))
  }, [pedido?.tipo, termo, busca.paginas, busca.atualizando])

  // O ↓ de fora da grade leva à primeira cena; dentro dela, as setas são da grade.
  useAtalhos([
    {
      tecla: '↓',
      acao: 'Ir à primeira cena do resultado; as setas andam entre as cenas',
      grupo: 'Busca',
      casa: (e) => e.key === 'ArrowDown' && busca.quantidade > 0 && !(e.target as Element | null)?.closest?.('[data-foco]'),
      executar: () => document.querySelector<HTMLElement>('[data-foco="0"]')?.focus(),
    },
    { tecla: 'Enter', acao: 'Abrir o vídeo no momento da cena', grupo: 'Busca' },
  ])

  const falha = busca.falha instanceof SessaoExpirada ? null : busca.falha
  const pronta = pedido !== null && !busca.carregando && !falha
  const linhaDoEntrando =
    entrando > 0 &&
    (entrando === 1 ? '1 vídeo ainda está entrando na busca e pode não aparecer aqui.' : `${entrando} vídeos ainda estão entrando na busca e podem não aparecer aqui.`)
  const proprios = pronta && avisos?.(busca)
  return (
    <GradeVirtual
      chave={busca.chave}
      voltaInicial={busca.voltaInicial}
      chegouNaVolta={busca.chegouNaVolta}
      recomecos={busca.recomecos}
      quantidade={busca.quantidade}
      aoVer={busca.aoVer}
      largura={LARGURA_DA_CENA}
      alturaDoTexto={TEXTO_DA_CENA}
      desenhar={(i) => {
        const cena = busca.item(i)
        return cena ? <Cena key={cena.chave} cena={cena} indice={i} busca={termo} /> : <EsqueletoDaCena key={`e${i}`} />
      }}
      esqueleto={<EsqueletoDaCena />}
      carregando={pedido && busca.carregando ? CARREGANDO[tipo] : null}
      cabecalho={
        <>
          {cabecalho(busca)}
          {pronta && (
            <div className="flex min-h-5 flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
              {busca.quantidade > 0 && <p role="status">{contagem(busca)}</p>}
              {busca.atualizando && (
                <p role="status" aria-label="Atualizando" className="flex items-center gap-1 text-xs">
                  <span className="size-2 animate-pulse rounded-full bg-andamento" aria-hidden /> Atualizando…
                </p>
              )}
            </div>
          )}
        </>
      }
      avisos={
        (linhaDoEntrando || proprios || busca.erroAoPaginar) && (
          <div className="grid gap-2 px-3 pt-3 md:px-4">
            {linhaDoEntrando && <p className="rounded-sm border border-andamento/40 bg-andamento/12 px-3 py-1 text-sm text-andamento">{linhaDoEntrando}</p>}
            {proprios}
            {busca.erroAoPaginar && <Falha mensagem="Não foi possível carregar mais cenas." codigo={busca.erroAoPaginar} aoTentar={busca.tentarDeNovo} />}
          </div>
        )
      }
    >
      {pedido === null && semPedido}
      {falha && (
        <div className="p-8">
          <Falha mensagem={mensagemDoErro(tipo, falha)} codigo={busca.erro} aoTentar={busca.tentarDeNovo} className="mx-auto max-w-xl" />
        </div>
      )}
      {pronta && busca.quantidade === 0 && <div className="grid justify-items-center gap-2 p-8 text-center text-muted-foreground">{vazio(busca)}</div>}
    </GradeVirtual>
  )
}

function contagemDaGrade(busca: ReturnType<typeof useBusca>, deCenas: (n: number) => string): string {
  // A quantidade conta um lugar a mais enquanto houver a página seguinte (o que a pede).
  const n = busca.quantidade - (busca.haMais ? 1 : 0)
  if (busca.haMais) return `Mais de ${deCenas(n)}`
  // Com as páginas do alto fora da memória, os vídeos de lá não se contam mais.
  if (!busca.primeiraNaMemoria) return deCenas(n)
  const videos = busca.paginas?.reduce((n, p) => n + p.videos.length, 0) ?? 0
  return `${deCenas(n)} em ${contagemDeVideos(videos)}`
}

/**
 * A página `/busca` da interface nova: o estado todo na URL e as cenas em grade (#400). A foto da
 * busca por imagem fica na memória da página, não na URL, e vale até "Limpar" ou até um texto novo.
 */
export function Busca({ consulta }: { consulta: ConsultaDaBusca }) {
  const [foto, setFoto] = useState<{ arquivo: File; id: number } | null>(null)
  const [arrastando, setArrastando] = useState(false)
  const campoDaFoto = useRef<HTMLInputElement>(null)
  const programas = useProgramas()
  const [texto, setTexto] = useState(consulta.q)
  const [termoVisto, setTermoVisto] = useState(consulta.q)
  // Um texto novo (desta caixa ou da busca do topo) sai da foto e busca o texto.
  if (termoVisto !== consulta.q) {
    setTermoVisto(consulta.q)
    setTexto(consulta.q)
    setFoto(null)
  }

  const pedido: PedidoDaBusca | null = foto
    ? { tipo: 'imagem', foto: foto.arquivo, id: foto.id, consulta }
    : consulta.q
      ? { tipo: 'texto', consulta }
      : null
  const mudar = (mudancas: Partial<ConsultaDaBusca>) => navegar(enderecoDaBusca({ ...consulta, ...mudancas }))
  function escolher(arquivo: File | undefined) {
    if (arquivo) setFoto({ arquivo, id: Date.now() })
    if (campoDaFoto.current) campoDaFoto.current.value = ''
  }

  return (
    <div
      className="contents"
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes('Files')) return
        e.preventDefault()
        setArrastando(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setArrastando(false)
      }}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return
        e.preventDefault()
        setArrastando(false)
        escolher(e.dataTransfer.files[0])
      }}
    >
      <GradeDaBusca
        pedido={pedido}
        termo={foto ? '' : consulta.q}
        semPedido={<p className="p-8 text-center text-muted-foreground">Escreva acima o que procurar no acervo, ou arraste a foto de um objeto (JPEG ou PNG) para achar onde ele aparece.</p>}
        cabecalho={(busca) => {
          const pagina = busca.paginas?.[0]
          const entendida = pagina?.entendida
          const facetas = pagina?.facetas
          // Os chips da URL valem sobre o entendido: um clique antes de a busca voltar não se perde.
          const ligadas = consulta.evidencias ?? entendida?.evidencias ?? []
          const alternar = (id: Evidencia) => mudar({ evidencias: ligadas.includes(id) ? ligadas.filter((e) => e !== id) : [...ligadas, id] })
          const programaNaTela = consulta.programa ?? entendida?.programa ?? ''
          const { desde, ate } = entendida ?? { desde: null, ate: null }
          const anoEntendido = desde && ate && desde.slice(0, 4) === ate.slice(0, 4) ? Number(desde.slice(0, 4)) : null
          // Um período entendido que não cabe num ano aparece como está; limpar o ano o tira.
          const periodoEntendido = consulta.ano === null && anoEntendido === null && (desde || ate) ? rotuloDoPeriodo(desde, ate) : null
          const anoNaTela = consulta.ano ?? anoEntendido
          const valorDoAno = periodoEntendido ? ENTENDIDO : typeof anoNaTela === 'number' ? String(anoNaTela) : null
          const anos = typeof anoNaTela === 'number' && !ANOS.includes(String(anoNaTela)) ? [String(anoNaTela), ...ANOS] : ANOS
          const comFacetas = facetas?.programa ?? []
          const opcoesDePrograma = [...opcoesDa(comFacetas), ...programas.filter((p) => !comFacetas.some((f) => f.valor === p)).map((p) => ({ valor: p, rotulo: p }))]
          const ligado: Record<Exclude<NomeDaFaceta, 'programa'>, string | null> = { mes: consulta.mes, pessoa: consulta.pessoa, marca: consulta.marca, tipo: consulta.tipo }
          return (
            <>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <h1 className="text-xl font-semibold">Busca</h1>
                <form
                  role="search"
                  className="relative w-full max-w-md min-w-0 sm:w-auto sm:flex-1"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (!texto.trim()) return
                    // O mesmo texto da URL não muda a consulta: a foto sai aqui.
                    setFoto(null)
                    navegar(enderecoDaBusca(consultaNova(texto.trim())))
                  }}
                >
                  <IconSearch size={16} className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <input
                    type="search"
                    maxLength={TAMANHO_DA_CONSULTA}
                    aria-label="Buscar no conteúdo"
                    placeholder="Falas, textos da tela, planos…"
                    value={texto}
                    onChange={(e) => setTexto(e.target.value)}
                    className="h-8 w-full rounded-sm border border-strong bg-input pr-2 pl-8 text-sm placeholder:text-subtle"
                  />
                </form>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  title="Arraste uma foto (JPEG ou PNG) ou escolha o arquivo."
                  onClick={() => campoDaFoto.current?.click()}
                  className={cn(arrastando && 'ring-2 ring-ring')}
                >
                  <IconPhotoSearch stroke={1.75} aria-hidden /> {arrastando ? 'Solte a foto' : 'Buscar por imagem'}
                </Button>
                <input
                  ref={campoDaFoto}
                  type="file"
                  accept="image/jpeg,image/png"
                  aria-label="Foto para buscar"
                  hidden
                  onChange={(e) => escolher(e.target.files?.[0])}
                />
              </div>
              {foto && (
                <div className="flex min-w-0 items-center gap-2 text-sm">
                  <IconPhotoSearch size={16} className="shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 truncate">{foto.arquivo.name}</span>
                  {entendida?.termo_da_foto && (
                    <span className="shrink-0 text-muted-foreground">
                      Buscando por: <strong className="font-medium text-foreground">{entendida.termo_da_foto}</strong>
                    </span>
                  )}
                  <Button type="button" variant="ghost" size="sm" onClick={() => setFoto(null)} className="text-link">
                    <IconX stroke={1.75} aria-hidden /> Limpar
                  </Button>
                </div>
              )}
              {pedido && (
                <div className="flex flex-wrap items-center gap-2">
                  {!foto && (
                    <>
                      <div role="group" aria-label="Tipo de evidência" className="flex flex-wrap items-center gap-2">
                        {EVIDENCIAS.map((e) => (
                          <Alternar
                            key={e.id}
                            ligado={ligadas.includes(e.id)}
                            cor={COR_DO_CHIP[e.tipo]}
                            // Sem nenhum chip ligado a busca voltaria ao entendido: o último fica.
                            desabilitado={ligadas.length === 1 && ligadas.includes(e.id)}
                            aoAlternar={() => alternar(e.id)}
                          >
                            {e.rotulo}
                          </Alternar>
                        ))}
                      </div>
                    </>
                  )}
                  <Faceta
                    rotulo="Programa"
                    Icone={IconBroadcast}
                    unico
                    opcoes={opcoesDePrograma}
                    valor={programaNaTela ? [programaNaTela] : []}
                    aoMudar={([p]) => mudar({ programa: p ?? '' })}
                  />
                  <Faceta
                    rotulo="Ano"
                    Icone={IconCalendarEvent}
                    unico
                    opcoes={[...(periodoEntendido ? [{ valor: ENTENDIDO, rotulo: periodoEntendido }] : []), ...anos.map((a) => ({ valor: a, rotulo: a }))]}
                    valor={valorDoAno ? [valorDoAno] : []}
                    aoMudar={([v]) => {
                      if (v !== ENTENDIDO) mudar({ ano: v ? Number(v) : 'todos', mes: null })
                    }}
                  />
                  {!foto &&
                    FACETAS.filter((f) => (facetas?.[f.nome].length ?? 0) > 0 || ligado[f.nome] !== null).map((f) => (
                      <Faceta
                        key={f.nome}
                        rotulo={f.rotulo}
                        Icone={f.Icone}
                        unico
                        opcoes={opcoesDa(facetas?.[f.nome] ?? [])}
                        valor={ligado[f.nome] !== null ? [ligado[f.nome]!] : []}
                        aoMudar={([v]) => mudar(f.nome === 'tipo' ? { tipo: (v ?? null) as TipoDeMomento | null } : { [f.nome]: v ?? null })}
                      />
                    ))}
                  {!foto && (
                    <div className="ml-auto">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button type="button" aria-label={`Ordenar por ${ORDENS[consulta.ordem].toLowerCase()}`} className="flex h-7 items-center gap-1 rounded-sm border border-strong bg-input px-2 text-sm">
                            <IconSortDescending size={16} stroke={1.75} className="text-muted-foreground" aria-hidden />
                            <span className="hidden sm:inline">{ORDENS[consulta.ordem]}</span>
                            <IconChevronDown size={14} className="opacity-60" aria-hidden />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuRadioGroup value={consulta.ordem} onValueChange={(v) => mudar({ ordem: v as OrdemDaBusca })}>
                            {Object.entries(ORDENS).map(([valor, rotulo]) => (
                              <DropdownMenuRadioItem key={valor} value={valor}>
                                {rotulo}
                              </DropdownMenuRadioItem>
                            ))}
                          </DropdownMenuRadioGroup>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  )}
                </div>
              )}
            </>
          )
        }}
        avisos={(busca) => {
          if (foto) return null
          const pagina = busca.paginas?.[0]
          if (!pagina) return null
          const ligadas = consulta.evidencias ?? pagina.entendida.evidencias
          return (
            <>
              {pagina.sem_aparicoes.map((s) => (
                <p key={s.pessoa_id ?? s.nome} className="flex flex-wrap items-center gap-2 text-sm">
                  <span>
                    Nenhuma aparição de {s.nome}.{s.mencoes_na_fala > 0 && ` ${contagemDeMencoes(s.mencoes_na_fala)} na fala.`}
                    {s.mencoes_na_tela > 0 && ` ${contagemDeMencoes(s.mencoes_na_tela)} na tela.`}
                  </span>
                  {s.mencoes_na_fala + s.mencoes_na_tela > 0 && (
                    <Button type="button" variant="secondary" size="sm" onClick={() => mudar({ evidencias: [...new Set<Evidencia>([...ligadas, 'citada', 'fala'])] })}>
                      Ver as menções
                    </Button>
                  )}
                </p>
              ))}
            </>
          )
        }}
        vazio={(busca) =>
          foto ? (
            <p role="status">
              Nenhum momento encontrado{busca.paginas?.[0]?.entendida.termo_da_foto && ` para “${busca.paginas[0].entendida.termo_da_foto}”`}. Tire um filtro, tente outra foto ou digite o que procura.
            </p>
          ) : busca.paginas?.[0]?.sem_aparicoes.length ? null : (
            <p>Nenhum momento encontrado para “{consulta.q}”. Tente outras palavras ou tire um filtro.</p>
          )
        }
        contagem={(busca) => contagemDaGrade(busca, contagemDeMomentos)}
      />
    </div>
  )
}
