// O jsdom não tem estas APIs, que o Mantine usa.
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

globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// O Select do Mantine rola até a opção ativa.
window.HTMLElement.prototype.scrollIntoView ??= () => {}
