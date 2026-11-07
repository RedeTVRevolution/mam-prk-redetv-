import { IconBox, IconMessage, IconMovie, IconTextCaption, type Icon } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { cn } from 'cn'
import { useId, useState, type MouseEvent } from 'react'
import { trechosDoMotivo, type Momento, type TipoDeMomento } from '../../busca.ts'
import { dataDeExibicao } from '../../jobs.ts'
import { relogio } from '../../linhaDoTempo.ts'
import { urlDoQuadroDaBusca } from '../../quadros.ts'
import { enderecoDoVideo, navegar, seguir } from '../../rotas.ts'
import { useApi } from '../consultas.ts'
import type { Cena as DadosDaCena } from './useBusca.ts'
import { urlSegura } from '../../urlSegura.ts'

/** A altura do cartão abaixo do quadro 16:9, para a estimativa antes de medir. */
export const TEXTO_DA_CENA = 90
// Acima disso (os GCs de regulamento), o motivo vem em 2 linhas, com "ver mais".
const MOTIVO_LONGO = 120

const TIPOS: Record<TipoDeMomento, { rotulo: string; cor: string; Icone: Icon }> = {
  plano: { rotulo: 'Plano', cor: 'text-tipo-aparicao', Icone: IconMovie },
  fala: { rotulo: 'Fala', cor: 'text-tipo-fala', Icone: IconMessage },
  texto_na_tela: { rotulo: 'GC', cor: 'text-tipo-texto', Icone: IconTextCaption },
  objeto: { rotulo: 'Objeto', cor: 'text-tipo-objeto', Icone: IconBox },
}

/** O quadro do momento: a URL assinada vem na resposta (chave de sistema) ou pela rota do quadro. */
function Quadro({ job, momento }: { job: string; momento: Momento }) {
  const api = useApi()
  const caminho = momento.quadro
  const pedida = useQuery({
    queryKey: ['quadro-da-busca', job, caminho],
    // O cache dos quadros (com a validade da URL) é o de quadros.ts; este só evita pedir de novo ao rolar.
    queryFn: () => urlDoQuadroDaBusca(api)(job, caminho!),
    enabled: !momento.quadro_url && !!caminho,
    retry: false,
  })
  const [falhou, setFalhou] = useState<string | null>(null)
  const url = urlSegura(momento.quadro_url ?? pedida.data)
  const tipo = TIPOS[momento.tipo]
  return (
    <span className="relative flex aspect-video w-full items-center justify-center overflow-hidden bg-canvas">
      {url && url !== falhou ? (
        <img src={url} alt="" loading="lazy" decoding="async" onError={() => setFalhou(url)} className="absolute inset-0 size-full object-cover" />
      ) : (
        // Sem quadro (a fala, o GC), o tipo do momento ocupa o lugar.
        <span className={cn('flex flex-col items-center gap-1 text-xs', tipo.cor)}>
          <tipo.Icone size={28} stroke={1.5} aria-hidden />
          {tipo.rotulo}
        </span>
      )}
      <span className="absolute right-1 bottom-1 rounded-xs bg-black/75 px-1 font-mono text-2xs text-white tabular-nums">{relogio(momento.inicio_ms)}</span>
    </span>
  )
}

/** O motivo com os trechos destacados, montado pelas posições: o texto nunca vira HTML. */
function Motivo({ momento, id, encurtado }: { momento: Momento; id: string; encurtado: boolean }) {
  return (
    <p id={id} className={cn('text-xs text-foreground/90', encurtado && 'line-clamp-2')}>
      {trechosDoMotivo(momento.motivo, momento.destaques).map((t, i) =>
        t.destacado ? (
          <mark key={i} className="rounded-xs bg-selected font-semibold text-foreground underline decoration-primary decoration-2 underline-offset-2">
            {t.texto}
          </mark>
        ) : (
          <span key={i}>{t.texto}</span>
        ),
      )}
    </p>
  )
}

/**
 * Um momento do resultado na grade (#400): o quadro (ou o tipo), o vídeo, o instante e o motivo.
 * O clique em qualquer lugar abre o vídeo no instante, menos no "ver mais".
 */
export function Cena({ cena, indice, busca }: { cena: DadosDaCena; indice: number; busca: string }) {
  const { video, momento } = cena
  const endereco = enderecoDoVideo(video.job_id, momento.inicio_ms / 1000, busca)
  const [aberto, setAberto] = useState(false)
  const idDoMotivo = useId()
  const longo = momento.motivo.length > MOTIVO_LONGO
  const aoClicar = (e: MouseEvent<HTMLElement>) => {
    if (e.defaultPrevented || (e.target as Element).closest('a, button')) return
    navegar(endereco)
  }
  return (
    <article onClick={aoClicar} className="flex min-w-0 cursor-pointer flex-col overflow-hidden rounded-sm bg-card ring-1 ring-transparent transition-shadow hover:ring-strong">
      {/* O nome é o link que entra no Tab; o quadro é o mesmo destino, só para o ponteiro. */}
      <a href={endereco} onClick={(e) => seguir(e, endereco)} tabIndex={-1} aria-hidden className="block">
        <Quadro job={video.job_id} momento={momento} />
      </a>
      <div className="grid gap-0.5 p-2">
        <h3 className="text-sm font-medium">
          <a
            href={endereco}
            onClick={(e) => seguir(e, endereco)}
            data-foco={indice}
            aria-label={`${video.nome} em ${relogio(momento.inicio_ms)}`}
            aria-describedby={idDoMotivo}
            title={video.nome}
            className="block truncate rounded-xs hover:underline"
          >
            {video.nome}
          </a>
        </h3>
        <p className="truncate text-xs text-muted-foreground">
          {video.programa ?? 'Sem programa'}
          {video.data_exibicao && `, ${dataDeExibicao(video.data_exibicao)}`}
        </p>
        <Motivo momento={momento} id={idDoMotivo} encurtado={longo && !aberto} />
        {longo && (
          <button type="button" aria-expanded={aberto} onClick={() => setAberto(!aberto)} className="justify-self-start rounded-xs text-xs text-link hover:underline">
            {aberto ? 'ver menos' : 'ver mais'}
          </button>
        )}
      </div>
    </article>
  )
}

/** O lugar de uma cena cuja página ainda não chegou (ou já saiu da memória). */
export function EsqueletoDaCena() {
  return (
    <div data-esqueleto className="flex flex-col overflow-hidden rounded-sm bg-card" aria-hidden>
      <div className="aspect-video bg-secondary" />
      <div className="grid gap-2 p-2" style={{ height: TEXTO_DA_CENA }}>
        <div className="h-3 w-2/3 rounded-xs bg-secondary" />
        <div className="h-3 w-1/2 rounded-xs bg-secondary" />
        <div className="h-3 w-5/6 rounded-xs bg-secondary" />
      </div>
    </div>
  )
}
