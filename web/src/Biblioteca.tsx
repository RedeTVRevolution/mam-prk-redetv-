import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import { validarArquivo } from './envio/arquivo.ts'
import { enviarRetomavel } from './envio/upload.ts'
import type { JobAberto } from './Video.tsx'

interface Job {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  criado_em: string
}

interface JobCriado extends Job {
  url_de_upload: string
}

type Envio =
  | { tipo: 'parado' }
  | { tipo: 'enviando'; fracao: number }
  | { tipo: 'concluido' }
  | { tipo: 'erro'; mensagem: string }

export default function Biblioteca({
  autenticador,
  aoSessaoExpirada,
  aoAbrir,
  intervaloMs = 5000,
}: {
  autenticador: Autenticador
  aoSessaoExpirada: () => void
  aoAbrir?: (job: JobAberto) => void
  intervaloMs?: number
}) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [envio, setEnvio] = useState<Envio>({ tipo: 'parado' })
  const [listaFalhou, setListaFalhou] = useState(false)

  const tratar = useCallback(
    (erro: unknown) => {
      if (erro instanceof SessaoExpirada) aoSessaoExpirada()
    },
    [aoSessaoExpirada],
  )

  const atualizar = useCallback(async () => {
    try {
      setJobs(await chamarApi<Job[]>(autenticador, '/v1/jobs'))
      setListaFalhou(false)
    } catch (erro) {
      tratar(erro)
      setListaFalhou(true)
    }
  }, [autenticador, tratar])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void atualizar()
    const relogio = setInterval(() => void atualizar(), intervaloMs)
    return () => clearInterval(relogio)
  }, [atualizar, intervaloMs])

  async function escolher(evento: ChangeEvent<HTMLInputElement>) {
    const campo = evento.currentTarget
    const arquivo = campo.files?.[0]
    campo.value = ''
    if (!arquivo) return
    const motivo = await validarArquivo(arquivo)
    if (motivo) {
      setEnvio({ tipo: 'erro', mensagem: motivo })
      return
    }
    setEnvio({ tipo: 'enviando', fracao: 0 })
    try {
      const criado = await chamarApi<JobCriado>(autenticador, '/v1/jobs', {
        metodo: 'POST',
        corpo: { nome: arquivo.name, tamanho_bytes: arquivo.size, tipo: arquivo.type },
      })
      void atualizar()
      await enviarRetomavel(criado.url_de_upload, arquivo, {
        aoProgresso: (fracao) => setEnvio({ tipo: 'enviando', fracao }),
      })
      setEnvio({ tipo: 'concluido' })
    } catch (erro) {
      tratar(erro)
      setEnvio({ tipo: 'erro', mensagem: 'Não foi possível enviar o vídeo.' })
    }
  }

  return (
    <section>
      <label>
        Enviar vídeo
        <input
          type="file"
          accept=".mp4,video/mp4"
          disabled={envio.tipo === 'enviando'}
          onChange={(e) => void escolher(e)}
        />
      </label>
      {envio.tipo === 'enviando' && (
        <progress aria-label="Progresso do envio" value={envio.fracao} max={1} />
      )}
      {envio.tipo === 'concluido' && <p>Envio concluído.</p>}
      {envio.tipo === 'erro' && <p role="alert">{envio.mensagem}</p>}
      {listaFalhou && (
        <p role="alert">Não foi possível atualizar a lista; tentando de novo.</p>
      )}
      {jobs?.length === 0 && <p>Nenhum vídeo enviado ainda.</p>}
      {jobs && jobs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Data</th>
              <th>Estado</th>
              <th>Código</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>
                  {aoAbrir && (job.estado === 'concluido' || job.estado === 'falhou') ? (
                    <button type="button" onClick={() => aoAbrir(job)}>
                      {job.nome}
                    </button>
                  ) : (
                    job.nome
                  )}
                </td>
                <td>{new Date(job.criado_em).toLocaleString('pt-BR')}</td>
                <td>{job.estado}</td>
                <td>{job.codigo_falha}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
