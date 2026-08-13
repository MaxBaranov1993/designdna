/* Опции шрифтов для селектов инспектора — JSX-порт fontOptionsHtml
 * (editor.js/inspector.js): каталог window.DesignAIFontCatalog с группами
 * или плоский fallback-список. Выбранное значение задаёт селект через defaultValue. */

const FALLBACK_FONTS = ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];

export function FontOptions({ autoLabel }: { autoLabel?: string }) {
  const catalog = window.DesignAIFontCatalog || null;
  return (
    <>
      {autoLabel != null ? <option value="">{autoLabel}</option> : null}
      {catalog && catalog.groups
        ? catalog.groups.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.fonts.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </optgroup>
          ))
        : (catalog ? catalog.families : FALLBACK_FONTS).map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
    </>
  );
}
