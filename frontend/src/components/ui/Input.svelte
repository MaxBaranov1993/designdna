<script lang="ts">
  import type { HTMLInputAttributes } from "svelte/elements";
  import { cn } from "../../lib/utils";

  // Рукописный примитив shadcn/ui Input — без внешних зависимостей
  let { class: className = undefined, ...rest }: HTMLInputAttributes = $props();
</script>

<input
  class={cn(
    "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors",
    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    "disabled:cursor-not-allowed disabled:opacity-50",
    className as string | undefined,
  )}
  {...rest}
/>
