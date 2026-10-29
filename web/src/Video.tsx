import { useCallback, useEffect, useRef, useState } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'

export interface JobAberto {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
}

interface Intervalo {
  inicio_ms: number
  fim_ms: number
}

interface Pessoa {
  id: string
  nome: string
  na_imagem: (Intervalo & { evidencia: string })[]
  citada_na_fala: Intervalo[]
  citada_no_texto: (Intervalo & { texto: string })[]
}

export interface Decupagem {
  pautas: (Intervalo & { titulo: string })[]
  pessoas: Pessoa[]
  planos: (Intervalo & { id: string; ambiente: string; acao?: string | null })[]
  comerciais: (Intervalo & { marca: string; tipo: string })[]
  transcricao: (Intervalo & { locutor: string; texto: string })[]
}

interface Reproducao {
  url: string
  expira_em: string
}

interface Item {
  chave: string
  inicio_ms: number
  rotulo: string
}

interface Grupo {
  titulo: string
  itens: Item[]
}

function tempo(ms: number): string {
  const total = Math.floor(ms / 1000)
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/** Separa pessoas na imagem, citadas na fala e citadas no texto (menção não é aparição). */
function agrupar(d: Decupagem): Grupo[] {
  const itens = <T extends Intervalo>(
    prefixo: string,
    lista: T[],
    rotulo: (x: T) => string,
  ): Item[] =>
    lista.map((x, i) => ({
      chave: `${prefixo}-${i}`,
      inicio_ms: x.inicio_ms,
      rotulo: rotulo(x),
    }))
  const dePessoas = <T extends Intervalo>(
    prefixo: string,
    escolher: (p: Pessoa) => T[],
    detalhe: (x: T) => string = () => '',
  ): Item[] =>
    d.pessoas.flatMap((p) =>
      itens(`${prefixo}-${p.id}`, escolher(p), (x) => p.nome + detalhe(x)),
    )
  return [
    { titulo: 'Pessoas na imagem', itens: dePessoas('img', (p) => p.na_imagem) },
    { titulo: 'Citadas na fala', itens: dePessoas('fala', (p) => p.citada_na_fala) },
    {
      titulo: 'Citadas no texto',
      itens: dePessoas('texto', (p) => p.citada_no_texto, (x) => ` — ${x.texto}`),
    },
    { titulo: 'Pautas', itens: itens('pauta', d.pautas, (x) => x.titulo) },
    {
      titulo: 'Planos',
      itens: itens('plano', d.planos, (x) => x.acao ?? x.ambiente),
    },
    {
      titulo: 'Comerciais',
      itens: itens('com', d.comerciais, (x) => `${x.marca} (${x.tipo})`),
    },
    {
      titulo: 'Transcrição',
      itens: itens('fala', d.transcricao, (x) => `${x.locutor}: ${x.texto}`),
    },
  ].filter((g) => g.itens.length > 0)
}

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'erro' }
  | { tipo: 'pronta'; reproducao: Reproducao; decupagem: Decupagem }

export default function Video({
  autenticador,
  job,
  aoVoltar,
  aoSessaoExpirada,
}: {
  autenticador: Autenticador
  job: JobAberto
  aoVoltar: () => void
  aoSessaoExpirada: () => void
}) {
  const player = useRef<HTMLVideoElement>(null)
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const concluido = job.estado === 'concluido'
  // O pai recria o callback a cada render; o efeito não deve recarregar por isso.
  const sessaoExpirada = useRef(aoSessaoExpirada)
  useEffect(() => {
    sessaoExpirada.current = aoSessaoExpirada
  })

  useEffect(() => {
    if (!concluido) return
    let ativo = true
    Promise.all([
      chamarApi<Reproducao>(autenticador, `/v1/jobs/${job.id}/reproducao`),
      chamarApi<Decupagem>(autenticador, `/v1/jobs/${job.id}/decupagem`),
    ]).then(
      ([reproducao, decupagem]) => {
        if (ativo) setCarga({ tipo: 'pronta', reproducao, decupagem })
      },
      (erro: unknown) => {
        if (!ativo) return
        if (erro instanceof SessaoExpirada) sessaoExpirada.current()
        else setCarga({ tipo: 'erro' })
      },
    )
    return () => {
      ativo = false
    }
  }, [autenticador, job.id, concluido])

  const retomarEm = useRef<number | null>(null)
  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e
  // continua do mesmo ponto.
  const renovarLink = useCallback(() => {
    if (carga.tipo !== 'pronta') return
    if (Date.parse(carga.reproducao.expira_em) > Date.now()) return
    const instante = player.current?.currentTime ?? 0
    chamarApi<Reproducao>(autenticador, `/v1/jobs/${job.id}/reproducao`).then(
      (reproducao) => {
        retomarEm.current = instante
        setCarga((atual) => (atual.tipo === 'pronta' ? { ...atual, reproducao } : atual))
      },
      (erro: unknown) => {
        if (erro instanceof SessaoExpirada) sessaoExpirada.current()
        else setCarga({ tipo: 'erro' })
      },
    )
  }, [autenticador, carga, job.id])
  const retomar = useCallback(() => {
    if (player.current && retomarEm.current !== null) {
      player.current.currentTime = retomarEm.current
      retomarEm.current = null
    }
  }, [])

  const saltar = useCallback((inicioMs: number) => {
    if (player.current) player.current.currentTime = inicioMs / 1000
  }, [])

  return (
    <section>
      <button type="button" onClick={aoVoltar}>
        Voltar à Biblioteca
      </button>
      <h2>{job.nome}</h2>
      {!concluido && (
        <p role="alert">
          {job.estado === 'falhou'
            ? `O vídeo falhou: ${job.codigo_falha ?? 'sem código'}`
            : 'O vídeo ainda não foi decupado.'}
        </p>
      )}
      {concluido && carga.tipo === 'carregando' && <p>Carregando…</p>}
      {concluido && carga.tipo === 'erro' && (
        <p role="alert">Não foi possível carregar o vídeo.</p>
      )}
      {carga.tipo === 'pronta' && concluido && (
        <div style={{ display: 'flex', gap: '1rem' }}>
          <video
            ref={player}
            src={carga.reproducao.url}
            controls
            onError={renovarLink}
            onLoadedMetadata={retomar}
            aria-label="Player"
            style={{ flex: 1, minWidth: 0 }}
          />
          <aside style={{ flex: 1, minWidth: 0 }} aria-label="Decupagem">
            <BaixarJson nome={job.nome} decupagem={carga.decupagem} />
            {agrupar(carga.decupagem).map((grupo) => (
              <section key={grupo.titulo} aria-label={grupo.titulo}>
                <h3>{grupo.titulo}</h3>
                <ul>
                  {grupo.itens.map((item) => (
                    <li key={item.chave}>
                      <button type="button" onClick={() => saltar(item.inicio_ms)}>
                        {tempo(item.inicio_ms)} {item.rotulo}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </aside>
        </div>
      )}
    </section>
  )
}

function BaixarJson({ nome, decupagem }: { nome: string; decupagem: Decupagem }) {
  function baixar() {
    const blob = new Blob([JSON.stringify(decupagem, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const ancora = document.createElement('a')
    ancora.href = url
    ancora.download = `${nome.replace(/\.mp4$/i, '')}.decupagem.json`
    ancora.click()
    // Revogar na hora pode cancelar o download em alguns navegadores.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return (
    <button type="button" onClick={baixar}>
      Baixar decupagem (JSON)
    </button>
  )
}
