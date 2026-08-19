<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLAttributes } from "svelte/elements";
  import { cn } from "../../lib/utils";

  let {
    class: className = undefined,
    children,
    ...rest
  }: HTMLAttributes<HTMLHeadingElement> & { children?: Snippet } = $props();
</script>

<h3 class={cn("text-sm font-semibold leading-none tracking-tight", className as string | undefined)} {...rest}>
  {@render children?.()}
</h3>
