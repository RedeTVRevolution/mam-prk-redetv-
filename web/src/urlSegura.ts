/**
 * O único filtro de endereço que vem de dado (capa, quadro, vídeo assinado, passo do Login) antes de
 * virar `href` ou `src`: só `https:` ou caminho relativo da própria aplicação. Qualquer outra coisa
 * (`javascript:`, `data:`, `http:`, `//outro.site`) volta `null`, e quem chama não renderiza o elemento.
 */
export function urlSegura(url: string | null | undefined): string | null {
  if (!url) return null
  // O navegador ignora tabulação, quebra de linha e espaços nas pontas ao ler o esquema.
  const limpa = Array.from(url).filter((c) => c.charCodeAt(0) > 0x20).join('')
  if (/^\/(?![/\\])/.test(limpa)) return url
  try {
    return new URL(limpa).protocol === 'https:' ? url : null
  } catch {
    return null
  }
}
