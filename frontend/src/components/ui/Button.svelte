<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";
  import { cn } from "../../lib/utils";

  // Рукописный примитив shadcn/ui Button — без radix/clsx и прочих зависимостей
  type Variant = "default" | "outline" | "ghost" | "secondary";
  type Size = "default" | "sm" | "icon";

  const variants: Record<Variant, string> = {
    default: "bg-primary text-primary-foreground hover:bg-primary/90",
    outline: "border border-input bg-transparent hover:bg-accent hover:text-accent-foreground",
    ghost: "hover:bg-accent hover:text-accent-foreground",
    secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  };

  const sizes: Record<Size, string> = {
    default: "h-9 px-4 py-2",
    sm: "h-8 px-3 text-xs",
    icon: "h-9 w-9",
  };

  let {
    variant = "default",
    size = "default",
    type = "button",
    class: className = undefined,
    children,
    ...rest
  }: HTMLButtonAttributes & {
    variant?: Variant;
    size?: Size;
    children?: Snippet;
  } = $props();
</script>

<button
  {type}
  class={cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors",
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    "disabled:pointer-events-none disabled:opacity-50",
    variants[variant as Variant],
    sizes[size as Size],
    className as string | undefined,
  )}
  {...rest}
>
  {@render children?.()}
</button>
