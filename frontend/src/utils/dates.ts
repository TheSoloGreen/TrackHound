/** Catalog/job timestamps without an offset are UTC, not browser-local time. */
export function parseServerDate(value: string): Date {
  return new Date(/(?:z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`)
}

export function formatServerDate(value: string): string {
  return parseServerDate(value).toLocaleString()
}
