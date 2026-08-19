<script lang="ts">
  import "@fontsource/inter/400.css";
  import "@fontsource/inter/500.css";
  import "@fontsource/inter/600.css";
  import "../index.css";
  import { installDesktopFetchBridge } from "../desktop/bridge";
  import { IRRenderer } from "../engine/renderer";
  import { getLoadedEditorController } from "../editor/runtime";

  let { children } = $props();

  // Стартовые window-хуки (зеркало main.tsx): desktop fetch bridge + read-only
  // хук сессии DNA-редактора для UI-тестов (вместо legacy window.Editor).
  // Модульный скрипт исполняется только в браузере (ssr = false).
  installDesktopFetchBridge();
  window.IRRenderer = IRRenderer;
  (window as unknown as { DNAEditor?: unknown }).DNAEditor = {
    getIR: () => {
      const s = getLoadedEditorController()?.getSession();
      return s ? s.activeIR || s.ir : null;
    },
    isOpen: () => getLoadedEditorController()?.isActive() ?? false,
  };
</script>

{@render children?.()}
