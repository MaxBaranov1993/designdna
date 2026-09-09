/** Read-only presentation of a captured kit. Never changes masters or invents evidence. */
export type KitSection = 'overview' | 'colors' | 'fonts' | 'concept';
export type KitEntry = { key: string; pool: 'components' | 'review' | 'suggestions'; component: Record<string, any> };
const COLOR_LABELS: Record<string, string> = {
  primary: 'Основной акцент', secondary: 'Дополнительный акцент', accent: 'Выделение',
  background: 'Фон страницы', surface: 'Поверхность', card: 'Карточка', text: 'Основной текст',
  foreground: 'Основной текст', textMuted: 'Вторичный текст', 'muted-foreground': 'Вторичный текст',
  border: 'Границы', 'primary-foreground': 'Текст на акценте', muted: 'Приглушённый фон',
};
export function kitColors(doc: Record<string, any>) {
  const semantic = doc.foundations?.colors?.semantic || {};
  const colors = Object.keys(semantic).length ? semantic : doc.styleGuide?.tokens || {};
  return Object.entries(colors).filter(([, v]) => typeof v === 'string' && /^(#[\da-f]{3,8}\b|(?:rgb|hsl|oklch|oklab|color)\()/i.test(v))
    .map(([key, value]) => ({ key, label: COLOR_LABELS[key] || key, value: String(value) }));
}
export function kitFonts(doc: Record<string, any>, entries: KitEntry[]) {
  const typography = doc.foundations?.typography || {};
  const faces = entries.flatMap(({ component }) => [component.masterIr,
    ...Object.values(component.variants || {}).map((v: any) => v.masterIr)])
    .flatMap(ir => ir?.meta?.fontFaces || []);
  const clean = (name: unknown) => String(name || '').replace(/^['"]|['"]$/g, '').trim();
  const families = [...new Set([...(typography.families || []), ...faces.map(f => f.family),
    typography.display?.family, typography.body?.family].map(clean).filter(Boolean))];
  return families.map(family => {
    const unique = new Map<string, any>();
    for (const face of faces.filter(f => clean(f.family) === family && typeof f.url === 'string')) {
      unique.set(JSON.stringify([face.url, face.weight, face.style, face.unicodeRange]), face);
    }
    const role = family === clean(typography.display?.family) ? 'Заголовки'
      : family === clean(typography.body?.family) ? 'Основной текст' : 'Дополнительный шрифт';
    return { family, role, faces: [...unique.values()] };
  });
}
export function kitConcept(doc: Record<string, any>) {
  const review = doc.styleGuide?.review;
  const fields = [['tone', 'Характер'], ['density', 'Плотность'], ['cornerCharacter', 'Формы'],
    ['colorUsage', 'Цвет'], ['typographyCharacter', 'Типографика'], ['imageryStyle', 'Изображения']];
  return {
    summary: String(doc.identity?.soul?.oneLine?.value || '').replace(/\btextMuted\b/g, 'вторичного текста').replace(/\btext\b/g, 'основного текста').replace(/\bbackground\b/g, 'фона'),
    traits: fields.filter(([key]) => typeof review?.[key] === 'string' && review[key])
      .map(([key, label]) => ({ label, text: String(review[key]) })),
    doRules: (Array.isArray(review?.doRules) ? review.doRules : []).filter((v: unknown) => typeof v === 'string'),
    dontRules: (Array.isArray(review?.dontRules) ? review.dontRules : []).filter((v: unknown) => typeof v === 'string'),
    hasAnalysis: !!review,
  };
}

/** Restrict font specimens to captured local assets; no network lookup/fallback download. */
export function capturedFontUrl(url: string, desktop: boolean): string | null {
  if (/^\/fonts\/[a-z\d_.-]+\.(woff2?|ttf|otf)$/i.test(url)) return desktop ? `ddna:/${url}` : url;
  if (/^ddna:\/\/fonts\/[a-z\d_.-]+\.(woff2?|ttf|otf)$/i.test(url)) return url;
  if (/^data:(font\/[\w.+-]+|application\/(?:font-woff|x-font-ttf|octet-stream));base64,[a-z\d+/=]+$/i.test(url)) return url;
  return null;
}
