/* Опции шрифтов для селектов инспектора — JSX-порт fontOptionsHtml:
 * каталог engine/fontCatalog с группами или плоский fallback-список.
 * Выбранное значение задаёт селект через defaultValue. */
import { DesignAIFontCatalog } from "../../engine/fontCatalog";

const FALLBACK_FONTS = ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];

export function FontOptions({ autoLabel }: { autoLabel?: string }) {
  const catalog = DesignAIFontCatalog;
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
