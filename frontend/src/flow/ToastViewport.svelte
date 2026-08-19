<script lang="ts">
  import { toastItems } from "./toast";
</script>

<!-- Контейнер тостов — зеркало #toasts в nodes.html -->
<div id="toasts">
  {#each $toastItems as t (t.id)}
    <div class={"toast" + (t.kind ? " " + t.kind : "")}>{t.msg}</div>
  {/each}
</div>
