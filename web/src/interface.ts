export type Interface = 'atual' | 'nova'

const CHAVE = 'mam:interface'

/**
 * A interface que o `main.tsx` carrega (ADR 0014): `?interface=nova` ou `?interface=atual` escolhe
 * e fica guardado no navegador; sem nada, vale a atual. O parâmetro sai do endereço depois de lido,
 * para não chegar aos filtros das telas.
 */
export function escolherInterface(): Interface {
  const url = new URL(location.href)
  const pedida = url.searchParams.get('interface')
  if (pedida === 'nova' || pedida === 'atual') {
    try {
      localStorage.setItem(CHAVE, pedida)
    } catch {
      // Sem armazenamento (modo privado, cota): vale só para esta carga.
    }
    url.searchParams.delete('interface')
    history.replaceState(history.state, '', url.pathname + url.search + url.hash)
    return pedida
  }
  try {
    return localStorage.getItem(CHAVE) === 'nova' ? 'nova' : 'atual'
  } catch {
    return 'atual'
  }
}

/** A mesma tela na interface atual. É um link de verdade: só a carga da página escolhe a interface. */
export function naInterfaceAtual(): string {
  const busca = new URLSearchParams(location.search)
  busca.set('interface', 'atual')
  return `${location.pathname}?${busca}${location.hash}`
}
