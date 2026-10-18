/** Compatibility for needs saved by earlier versions; provenance is shown separately. */
export function personaNeedText(value: string): string {
  return value.replace(/^\s*hip[oó]tesis por validar\s*:\s*/i, "");
}
