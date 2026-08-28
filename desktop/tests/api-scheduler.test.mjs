import test from "node:test";
import assert from "node:assert/strict";
import { ApiScheduler, Semaphore } from "../services/api-scheduler.mjs";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

test("медленный запрос не блокирует параллельную полосу", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: ["/api/block-parse"] });
  const worker = {};
  scheduler.registerWorker(worker, 3);

  const slow = deferred();
  const slowDone = scheduler.run("/api/generate", worker, () => slow.promise);
  const fastResult = await scheduler.run("/api/config", worker, async () => "fast");
  assert.equal(fastResult, "fast");

  slow.resolve("slow");
  assert.equal(await slowDone, "slow");
});

test("семафор ограничивает параллельность лимитом воркера", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: [] });
  const worker = {};
  scheduler.registerWorker(worker, 2);

  let active = 0;
  let peak = 0;
  const gate = deferred();
  const job = async () => {
    active += 1;
    peak = Math.max(peak, active);
    await gate.promise;
    active -= 1;
    return peak;
  };
  const jobs = [1, 2, 3, 4].map(() => scheduler.run("/api/x", worker, job));
  await tick();
  assert.equal(active, 2, "третий и четвёртый запросы ждут слота");
  gate.resolve();
  await Promise.all(jobs);
  assert.equal(peak, 2);
  assert.equal(active, 0);
});

test("exclusive-полоса строго серийная", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: ["/api/block-parse"] });
  const worker = {};
  const order = [];
  const first = deferred();
  const a = scheduler.run("/api/block-parse", worker, async () => {
    await first.promise;
    order.push("a");
  });
  const b = scheduler.run("/api/block-parse", worker, async () => {
    order.push("b");
  });
  await tick();
  assert.deepEqual(order, [], "второй ждёт первого");
  first.resolve();
  await Promise.all([a, b]);
  assert.deepEqual(order, ["a", "b"]);
});

test("project-полоса серийная, но не задерживает параллельную", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: [] });
  const worker = {};
  scheduler.registerWorker(worker, 2);

  const saveGate = deferred();
  const order = [];
  const save1 = scheduler.run("/api/project/save", worker, async () => {
    await saveGate.promise;
    order.push("save1");
  });
  const save2 = scheduler.run("/api/project/save", worker, async () => {
    order.push("save2");
  });
  // Параллельная полоса не ждёт project-очередь
  const light = await scheduler.run("/api/config", worker, async () => "light");
  assert.equal(light, "light");
  assert.deepEqual(order, []);

  saveGate.resolve();
  await Promise.all([save1, save2]);
  assert.deepEqual(order, ["save1", "save2"], "сейвы идут по одному, по порядку");
});

test("упавшая операция не ломает полосу и пробрасывает ошибку", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: [] });
  const worker = {};
  scheduler.registerWorker(worker, 1);

  await assert.rejects(
    () => scheduler.run("/api/x", worker, async () => { throw new Error("boom"); }),
    /boom/,
  );
  assert.equal(await scheduler.run("/api/x", worker, async () => "ok"), "ok");
  await assert.rejects(
    () => scheduler.run("/api/project/save", worker, async () => { throw new Error("save-boom"); }),
    /save-boom/,
  );
  assert.equal(await scheduler.run("/api/project/load", worker, async () => "ok2"), "ok2");
});

test("Semaphore: воркер без registerWorker получает дефолтный лимит", async () => {
  const scheduler = new ApiScheduler({ exclusivePaths: [] });
  const results = await Promise.all(
    [1, 2, 3].map((n) => scheduler.run("/api/x", {}, async () => n)),
  );
  assert.deepEqual(results, [1, 2, 3]);
});

test("Semaphore напрямую: возвращает результат и снимает слот при ошибке", async () => {
  const semaphore = new Semaphore(1);
  await assert.rejects(() => semaphore.run(async () => { throw new Error("x"); }), /x/);
  assert.equal(await semaphore.run(async () => 42), 42);
});
