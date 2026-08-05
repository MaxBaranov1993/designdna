// Минимальная замена clsx: склеивает классы, пропуская пустые значения
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
