// O jsdom não tem o `matchMedia`, que a interface (a barra lateral, por exemplo) consulta.
window.matchMedia ??= (consulta: string) =>
  ({
    matches: false,
    media: consulta,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList

// O recharts só desenha quando o ResizeObserver informa um tamanho; o jsdom não mede nada.
globalThis.ResizeObserver ??= class {
  aviso: ResizeObserverCallback
  constructor(aviso: ResizeObserverCallback) {
    this.aviso = aviso
  }
  observe(alvo: Element) {
    const contentRect = { width: 800, height: 400 } as DOMRectReadOnly
    this.aviso([{ target: alvo, contentRect } as ResizeObserverEntry], this as unknown as ResizeObserver)
  }
  unobserve() {}
  disconnect() {}
}

// O jsdom não rola: as telas chamam `scrollIntoView` na linha ativa das listas.
window.HTMLElement.prototype.scrollIntoView ??= () => {}
