import { PedidoInvalido } from '../api.ts'

// Conveniência: a API e a validação da quarentena repetem estas conferências.

export const TAMANHO_MAXIMO_BYTES = 4 * 1024 ** 3
const MARCAS_PERMITIDAS = ['isom', 'mp41', 'mp42', 'avc1']

function texto(bytes: Uint8Array, de: number, ate: number) {
  return new TextDecoder('latin1').decode(bytes.slice(de, ate))
}

/** Devolve o motivo da recusa, ou null se o arquivo pode ser enviado. */
export async function validarArquivo(arquivo: File): Promise<string | null> {
  if (!arquivo.name.toLowerCase().endsWith('.mp4')) return 'O arquivo precisa ter a extensão .mp4.'
  if (arquivo.type !== 'video/mp4') return 'O arquivo precisa ser do tipo video/mp4.'
  if (arquivo.size === 0) return 'O arquivo está vazio.'
  if (arquivo.size > TAMANHO_MAXIMO_BYTES) return 'O arquivo passa do tamanho máximo de 4 GiB.'
  const cabecalho = new Uint8Array(await arquivo.slice(0, 12).arrayBuffer())
  if (texto(cabecalho, 4, 8) !== 'ftyp' || !MARCAS_PERMITIDAS.includes(texto(cabecalho, 8, 12))) {
    return 'O arquivo não parece um MP4 válido.'
  }
  return null
}

/** Hoje, no fuso da emissora: a API recusa data de exibição no futuro. */
export function hoje(): string {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'America/Sao_Paulo' })
}

export function mensagemDoErroDoEnvio(erro: unknown): string {
  if (erro instanceof PedidoInvalido && erro.message === 'Data de exibição no futuro') {
    return 'A data de exibição não pode ser no futuro. Corrija a data e envie de novo.'
  }
  return 'Não foi possível enviar o vídeo. Tente de novo.'
}
