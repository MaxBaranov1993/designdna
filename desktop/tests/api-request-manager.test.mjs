import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiRequestManager } from '../services/api-request-manager.mjs';
import { ApiScheduler } from '../services/api-scheduler.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));
test('cancelling active and queued requests never restarts a worker or releases its running slot early', async () => {
  const manager = new ApiRequestManager(), scheduler = new ApiScheduler();
  const pending = [], cancelled = [];
  const worker = {
    request(_method, params, _timeout, options) {
      return new Promise(resolve => pending.push({ params, options, resolve }));
    },
    sendControl(frame) { cancelled.push(frame.requestId); return true; },
    abort() { assert.fail('a node cannot abort the shared process'); },
  };
  scheduler.registerWorker(worker, 2);
  const run = id => manager.run(id, 'long', worker, ({ signal, dispatch }) =>
    scheduler.run('/api/generate', worker, () => dispatch({ id }, 600_000), signal));
  const a = run('page-A:1'), b = run('page-B:1');
  await tick();
  const queued = run('page-C:1');
  const rejectedQueue = assert.rejects(queued, /cancelled/);
  assert.equal(manager.cancel('page-C:1').mode, 'queued');
  await rejectedQueue;
  const rejectedA = assert.rejects(a, /cancelled/);
  assert.equal(manager.cancel('page-A:1').mode, 'cooperative');
  await rejectedA;
  const d = run('page-D:1'); await tick();
  assert.deepEqual(pending.map(x => x.params.id), ['page-A:1', 'page-B:1']);
  assert.deepEqual(cancelled, [pending[0].options.id]);
  pending[1].resolve('B result'); assert.equal(await b, 'B result'); await tick();
  assert.equal(pending[2].params.id, 'page-D:1');
  pending[0].resolve('late A result'); pending[2].resolve('D result');
  assert.equal(await d, 'D result'); await tick();
  assert.equal(manager.requests.size, 0);
  assert.equal(manager.cancel('page-B:1').cancelled, false);
  assert.equal(manager.cancel('').cancelled, false);
});

test('control requests stay available when every long slot is occupied', async () => {
  const scheduler = new ApiScheduler(), worker = {};
  scheduler.registerWorker(worker, 1);
  let release;
  const busy = scheduler.run('/api/generate', worker, () => new Promise(resolve => { release = resolve; }));
  const progress = await scheduler.run('/api/block-parse/job/source-1', worker, async () => 72);
  assert.equal(progress, 72);
  assert.equal(await scheduler.run('/api/block-parse/job/source-1/cancel', worker, async () => 'cancelled'), 'cancelled');
  assert.equal(scheduler.lane('/api/timeline/render/job/download'), 'concurrent');
  release(); await busy;
});

test('cancellation in the wake-up turn cannot strand a semaphore queue', async () => {
  const scheduler = new ApiScheduler(), worker = {}, controller = new AbortController();
  scheduler.registerWorker(worker, 1);
  let release;
  const a = scheduler.run('/api/x', worker, () => new Promise(resolve => { release = resolve; }));
  const b = scheduler.run('/api/x', worker, () => assert.fail('cancelled operation started'), controller.signal);
  const rejected = assert.rejects(b, { name: 'AbortError' });
  const c = scheduler.run('/api/x', worker, () => 'next');
  release(); controller.abort();
  await a; await rejected; assert.equal(await c, 'next');
});
