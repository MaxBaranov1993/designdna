<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLAttributes } from "svelte/elements";
  import { cn } from "../../lib/utils";

  // Рукописный примитив shadcn/ui Card — без внешних зависимостей
  let {
    class: className = undefined,
    children,
    ...rest
  }: HTMLAttributes<HTMLDivElement> & { children?: Snippet } = $props();
</script>

<div class={cn("rounded-lg border bg-card text-card-foreground", className as string | undefined)} {...rest}>
  {@render children?.()}
</div>
