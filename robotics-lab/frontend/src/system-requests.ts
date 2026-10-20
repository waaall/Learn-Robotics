// 统一系统状态请求、会话操作和发布顺序；过期响应即使未被取消，也不能重新发布。
export type SessionChange = symbol;
type StateUpdate<T> = (previous: T | null) => T | null;

export class SystemRequests<T> {
  private epoch = 0;
  private nextRequest = 0;
  private appliedRequest = 0;
  private publication = 0;
  private activeChange: SessionChange | null = null;
  private pending = new Map<number, AbortController>();
  private snapshot: T | null = null;

  constructor(
    private fetchSystem: (signal: AbortSignal) => Promise<T>,
    private publish: (update: StateUpdate<T>) => void,
  ) {}

  current() { return this.snapshot; }

  private apply(update: StateUpdate<T>) {
    this.snapshot = update(this.snapshot);
    const snapshot = this.snapshot;
    const publication = ++this.publication;
    // React 可以稍后处理更新；已经排队的旧发布也需要失效。
    this.publish(previous => publication === this.publication ? snapshot : previous);
  }

  private cancelReads() {
    this.epoch++;
    for (const controller of this.pending.values()) controller.abort();
    this.pending.clear();
  }

  cancel() {
    this.cancelReads();
    this.publication++;
    this.activeChange = null;
  }

  async read({ signal, change }: { signal?: AbortSignal; change?: SessionChange } = {}): Promise<T | null> {
    if (signal?.aborted || (this.activeChange !== null && change !== this.activeChange)
      || (change !== undefined && change !== this.activeChange)) return null;
    const epoch = this.epoch;
    const request = ++this.nextRequest;
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    this.pending.set(request, controller);
    const valid = () => epoch === this.epoch && !controller.signal.aborted;
    try {
      const result = await this.fetchSystem(controller.signal);
      if (!valid() || request < this.appliedRequest) return null;
      this.appliedRequest = request;
      this.apply(() => result);
      return result;
    } catch (error) {
      if (!valid()) return null;
      throw error;
    } finally {
      signal?.removeEventListener("abort", abort);
      this.pending.delete(request);
    }
  }

  update(update: StateUpdate<T>, change: SessionChange) {
    if (change !== this.activeChange) throw new Error("会话操作已失效");
    this.apply(update);
  }

  async change<R>(operation: (change: SessionChange) => Promise<R>): Promise<R> {
    if (this.activeChange !== null) throw new Error("会话操作正在进行");
    const change = Symbol("session-change");
    this.cancelReads();
    this.publication++;
    this.activeChange = change;
    try {
      return await operation(change);
    } finally {
      if (this.activeChange === change) {
        // 操作结束后再推进代次，随后恢复普通轮询，保留操作已经发布的有效状态。
        this.cancelReads();
        this.activeChange = null;
      }
    }
  }
}
