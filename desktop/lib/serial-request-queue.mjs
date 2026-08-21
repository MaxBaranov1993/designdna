export class SerialRequestQueue {
  constructor() {
    this.tail = Promise.resolve();
  }

  run(operation) {
    const pending = this.tail.then(operation, operation);
    this.tail = pending.catch(() => undefined);
    return pending;
  }
}
