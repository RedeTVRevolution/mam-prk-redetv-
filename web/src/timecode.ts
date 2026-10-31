// Timecode SMPTE do quadro atual: o TC de origem do arquivo somado ao tempo do player.

const QUADROS_PERDIDOS_POR_MINUTO = 2

function partes(tc: string): { h: number; m: number; s: number; f: number; drop: boolean } | null {
  const achado = /^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$/.exec(tc)
  if (!achado) return null
  return { h: +achado[1], m: +achado[2], s: +achado[3], f: +achado[5], drop: achado[4] === ';' }
}

/**
 * O TC no instante `ms` do arquivo, dado o TC do primeiro quadro e a taxa real de quadros.
 * `HH:MM:SS;FF` (ponto e vírgula) é drop-frame (29,97 fps, regra SMPTE: pula os quadros 00 e 01
 * a cada minuto, menos nos múltiplos de 10). Devolve `null` se o TC inicial não estiver no formato
 * ou se for drop-frame numa taxa que não seja 29,97.
 */
export function timecodeNoInstante(inicial: string, fps: number, ms: number): string | null {
  const p = partes(inicial)
  if (!p || !(fps > 0)) return null
  const base = Math.round(fps)
  // A regra de 2 quadros por minuto só vale para 29,97; noutra taxa, o TC sairia errado sem aviso.
  if (p.drop && base !== 30) return null
  const porMinuto = base * 60 - QUADROS_PERDIDOS_POR_MINUTO
  const porDezMinutos = base * 600 - 9 * QUADROS_PERDIDOS_POR_MINUTO
  const minutosInicio = p.h * 60 + p.m
  let quadros = (p.h * 3600 + p.m * 60 + p.s) * base + p.f
  if (p.drop) quadros -= QUADROS_PERDIDOS_POR_MINUTO * (minutosInicio - Math.floor(minutosInicio / 10))
  // O épsilon cobre o erro de ponto flutuante de quem calcula o instante a partir do quadro.
  quadros += Math.floor((Math.max(ms, 0) * fps) / 1000 + 1e-6)

  let exibido = quadros
  if (p.drop) {
    const blocos = Math.floor(quadros / porDezMinutos)
    const resto = quadros % porDezMinutos
    exibido += 9 * QUADROS_PERDIDOS_POR_MINUTO * blocos
    if (resto >= QUADROS_PERDIDOS_POR_MINUTO) {
      exibido += QUADROS_PERDIDOS_POR_MINUTO * Math.floor((resto - QUADROS_PERDIDOS_POR_MINUTO) / porMinuto)
    }
  }
  const dois = (n: number) => String(n).padStart(2, '0')
  const f = exibido % base
  const s = Math.floor(exibido / base) % 60
  const m = Math.floor(exibido / (base * 60)) % 60
  const h = Math.floor(exibido / (base * 3600)) % 24
  return `${dois(h)}:${dois(m)}:${dois(s)}${p.drop ? ';' : ':'}${dois(f)}`
}
