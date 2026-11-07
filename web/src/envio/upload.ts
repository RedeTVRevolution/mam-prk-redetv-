// Upload retomável do Cloud Storage (protocolo "resumable"): abre a sessão na URL
// assinada e envia pedaços com Content-Range; após uma falha, pergunta ao Storage
// até onde chegou e continua dali.

const PEDACO_PADRAO = 8 * 1024 * 1024 // múltiplo de 256 KiB, como o Storage exige

export interface OpcoesDoUpload {
  tamanhoDoPedaco?: number
  /** Falhas seguidas toleradas antes de desistir. */
  tentativas?: number
  /** Fração enviada, de 0 a 1. */
  aoProgresso?: (fracao: number) => void
  espera?: (ms: number) => Promise<void>
}

export class UploadFalhou extends Error {}

/** Erro 4xx definitivo (sessão expirada ou cancelada, pedido recusado): tentar de novo não adianta. */
class SessaoPerdida extends UploadFalhou {}

function definitivo(status: number) {
  return status >= 400 && status < 500 && status !== 408 && status !== 429
}

function dormir(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

function bytesRecebidos(resposta: Response) {
  const faixa = /^bytes=0-(\d+)$/.exec(resposta.headers.get('Range') ?? '')
  return faixa ? Number(faixa[1]) + 1 : 0
}

export async function enviarRetomavel(
  urlAssinada: string,
  arquivo: File,
  opcoes: OpcoesDoUpload = {},
): Promise<void> {
  const { tamanhoDoPedaco = PEDACO_PADRAO, tentativas = 5, aoProgresso, espera = dormir } = opcoes
  const total = arquivo.size

  const abertura = await fetch(urlAssinada, {
    method: 'POST',
    headers: {
      'x-goog-resumable': 'start',
      // Objeto escrito uma vez só: a URL assina este cabeçalho (#369).
      'x-goog-if-generation-match': '0',
      'Content-Type': arquivo.type,
      // Tamanho declarado: a URL assinada pode prender a sessão a ele.
      'x-upload-content-length': String(total),
    },
  })
  const sessao = abertura.headers.get('Location')
  if (!abertura.ok || !sessao) throw new UploadFalhou('Não foi possível abrir o upload')

  let enviado = 0
  let falhas = 0
  while (enviado < total) {
    try {
      const fim = Math.min(enviado + tamanhoDoPedaco, total)
      const resposta = await fetch(sessao, {
        method: 'PUT',
        headers: { 'Content-Range': `bytes ${enviado}-${fim - 1}/${total}` },
        body: arquivo.slice(enviado, fim),
      })
      if (resposta.status === 308) enviado = bytesRecebidos(resposta)
      else if (resposta.ok) enviado = total
      else if (definitivo(resposta.status)) throw new SessaoPerdida(`Falha ${resposta.status} no upload`)
      else throw new UploadFalhou(`Falha ${resposta.status} no upload`)
      falhas = 0
      aoProgresso?.(enviado / total)
    } catch (erro) {
      if (erro instanceof SessaoPerdida) throw erro
      falhas += 1
      if (falhas >= tentativas) throw new UploadFalhou('O upload foi interrompido')
      await espera(500 * 2 ** (falhas - 1))
      enviado = await perguntarOndeParou(sessao, total, enviado)
    }
  }
}

/** Sem resposta útil do Storage, segue do ponto que já se conhecia. */
async function perguntarOndeParou(sessao: string, total: number, conhecido: number): Promise<number> {
  let resposta: Response
  try {
    resposta = await fetch(sessao, {
      method: 'PUT',
      headers: { 'Content-Range': `bytes */${total}` },
    })
  } catch {
    return conhecido
  }
  if (resposta.ok) return total
  if (resposta.status === 308) return bytesRecebidos(resposta)
  if (definitivo(resposta.status)) throw new SessaoPerdida(`Falha ${resposta.status} no upload`)
  return conhecido
}
