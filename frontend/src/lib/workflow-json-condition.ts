const PREFIX = 'json_string_equals:';

export function isJsonTextCondition(expression: string): boolean {
  return expression.startsWith(PREFIX);
}

export function readJsonTextCondition(expression: string): { key: string; value: string } | null {
  if (!isJsonTextCondition(expression)) return null;
  try {
    const parsed = JSON.parse(expression.slice(PREFIX.length));
    return typeof parsed?.key === 'string' && typeof parsed.value === 'string'
      ? { key: parsed.key, value: parsed.value } : null;
  } catch {
    return null;
  }
}

export function jsonTextCondition(key: string, value: string): string {
  return PREFIX + JSON.stringify({ key, value });
}
