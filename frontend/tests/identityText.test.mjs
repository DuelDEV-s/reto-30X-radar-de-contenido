import test from "node:test";
import assert from "node:assert/strict";
import { personaNeedText } from "../src/identityText.ts";

test("legacy persona needs omit the generated prefix while preserving the team's text", () => {
  assert.equal(personaNeedText("Hipótesis por validar: Encontrar piezas de colección."), "Encontrar piezas de colección.");
  assert.equal(personaNeedText("  HIPOTESIS POR VALIDAR : Conocer series sin spoilers."), "Conocer series sin spoilers.");
  assert.equal(personaNeedText("Evaluar una hipótesis por validar con el equipo."), "Evaluar una hipótesis por validar con el equipo.");
  assert.equal(personaNeedText("Encontrar productos para decorar."), "Encontrar productos para decorar.");
});
