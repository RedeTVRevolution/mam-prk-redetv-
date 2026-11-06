import { expect, test } from "vitest";
import { passoDaEscala } from "./escala.ts";

// A matriz marca × tipo usa a escala sequencial do design system (2.6): o maior valor é o passo mais claro, e o zero é a superfície, sem cor.
test("zero não tem cor, e o maior valor é o passo mais claro", () => {
  expect(passoDaEscala(0, 100)).toBeNull();
  expect(passoDaEscala(10, 0)).toBeNull();
  expect(passoDaEscala(100, 100)).toBe(100);
});

test("os cinco passos dividem a escala em quintos, do mais escuro (menor) ao mais claro", () => {
  expect([1, 20, 21, 40, 41, 60, 61, 80, 81, 100].map((v) => passoDaEscala(v, 100))).toEqual([
    600, 600, 500, 500, 400, 400, 250, 250, 100, 100,
  ]);
});
