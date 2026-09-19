'use strict';
// Pythonの常駐ワーカー（`python -m text_compositor.worker`）を、サブプロセスとして起動し、標準入出力のJSON行
// （プロトコル1。仕様書14章）で依頼するクライアント（#190）。
//
// ワーカーは、依頼を1つずつ順に処理するため、ここでも1つずつ直列に送る。ワーカーが終了した場合（クラッシュ等）は、
// 待っている依頼を例外で失敗させ、次の依頼のときに、起動し直す。依頼が時間切れになった場合は、ワーカーが
// ビルドの途中の可能性があるため、終了させて、次の依頼のときに、起動し直す。

const { spawn } = require('node:child_process');
const readline = require('node:readline');

class WorkerError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = 'WorkerError';
  }
}

/** ワーカーが、プロトコルの誤りとして依頼を拒否した（`error`キーつきの応答）。依頼は処理されていない。 */
class WorkerProtocolError extends WorkerError {
  constructor(code, message) {
    super(`${code}: ${message}`);
    this.name = 'WorkerProtocolError';
    this.code = code;
  }
}

const STDERR_TAIL_LINES = 40;

class WorkerClient {
  /**
   * @param {{file: string, args: string[], env?: Record<string,string>, cwd?: string}} launch
   * @param {{startTimeoutMs?: number, requestTimeoutMs?: number}} [options]
   */
  constructor(launch, options = {}) {
    this._launch = launch;
    this._startTimeoutMs = options.startTimeoutMs ?? 60_000;
    this._requestTimeoutMs = options.requestTimeoutMs ?? 300_000;
    this._proc = null;
    this._ready = null;
    this._pending = new Map();
    this._stderr = [];
    this._nextId = 0;
    this._queue = Promise.resolve();
    this._disposed = false;
    this.startCount = 0;
  }

  /** ワーカーのプロセスが動いているか。 */
  get isRunning() {
    return this._proc !== null && this._proc.exitCode === null && !this._proc.killed;
  }

  /** ワーカーの標準エラーの末尾（診断用）。 */
  get stderrTail() {
    return this._stderr.join('\n');
  }

  /** ワーカーを先に起動しておく（最初の依頼の待ち時間を短くする）。 */
  warmUp() {
    return this._ensureStarted();
  }

  /**
   * Markdown（または図の単体ファイル）をHTMLにする。ビルドの失敗は、結果（ok: false）で返す。
   * ワーカー自体の異常は、例外で返す。
   * @param {{path: string, output?: string, plugins?: object, variables?: object, config?: object}} params
   * @returns {Promise<{ok: boolean, html: string|null, diagnostics: object[], timings_ms: object}>}
   */
  async renderHtml(params) {
    const response = await this._request('render_html', params);
    if (response.error) throw new WorkerProtocolError(response.error.code ?? 'error', response.error.message ?? '');
    return {
      ok: response.ok === true,
      html: response.html ?? null,
      diagnostics: response.diagnostics ?? [],
      timings_ms: response.timings_ms ?? {},
    };
  }

  /** 生存確認。 */
  async ping() {
    const response = await this._request('ping', {});
    if (response.error) throw new WorkerProtocolError(response.error.code ?? 'error', response.error.message ?? '');
    return response.ok === true;
  }

  /** ワーカーに終了を依頼し、応答がなければ、強制終了する。 */
  async dispose() {
    if (this._disposed) return;
    this._disposed = true;
    const proc = this._proc;
    if (!proc || !this.isRunning) return;
    const exited = new Promise((resolve) => proc.once('exit', resolve));
    try {
      proc.stdin.write('{"id":0,"method":"shutdown"}\n');
    } catch {
      /* すでに閉じている */
    }
    const timer = setTimeout(() => killTree(proc), 5000);
    await exited;
    clearTimeout(timer);
  }

  // ---------------------------------------------------------------------

  _request(method, params) {
    if (this._disposed) return Promise.reject(new WorkerError('ワーカーは、すでに終了しています。'));
    // 依頼は、直列に処理する。前の依頼が失敗しても、次の依頼は、続けて処理する。
    const run = () => this._send(method, params);
    const result = this._queue.then(run, run);
    this._queue = result.catch(() => {});
    return result;
  }

  async _send(method, params) {
    await this._ensureStarted();
    const proc = this._proc;
    const id = ++this._nextId;
    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._pending.delete(id);
        this._discard(proc);
        reject(new WorkerError(`ワーカーが ${Math.round(this._requestTimeoutMs / 1000)} 秒以内に応答しませんでした。`));
      }, this._requestTimeoutMs);
      this._pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
    });
    try {
      proc.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    } catch (error) {
      this._pending.get(id)?.reject(new WorkerError('ワーカーへの書き込みに失敗しました。' + this._tail(), { cause: error }));
      this._pending.delete(id);
    }
    return response;
  }

  _ensureStarted() {
    if (this._disposed) return Promise.reject(new WorkerError('ワーカーは、すでに終了しています。'));
    if (this._ready && this.isRunning) return this._ready;
    this._ready = this._start();
    // 起動に失敗しても、未処理の拒否として扱われないようにする（呼び出し側が、await して受け取る）
    this._ready.catch(() => {});
    return this._ready;
  }

  _start() {
    const { file, args, env, cwd } = this._launch;
    return new Promise((resolve, reject) => {
      let proc;
      try {
        proc = spawn(file, args, {
          cwd,
          env: { ...process.env, PYTHONUTF8: '1', ...env },
          stdio: ['pipe', 'pipe', 'pipe'],
          windowsHide: true,
        });
      } catch (error) {
        reject(new WorkerError(`ワーカーを起動できませんでした（${file}）: ${error.message}`, { cause: error }));
        return;
      }
      this._proc = proc;
      this._stderr = [];
      this.startCount += 1;
      let settled = false;
      const settle = (fn, value) => { if (!settled) { settled = true; clearTimeout(startTimer); fn(value); } };

      const startTimer = setTimeout(() => {
        this._discard(proc);
        settle(reject, new WorkerError(`ワーカーが ${Math.round(this._startTimeoutMs / 1000)} 秒以内に準備できませんでした。${this._tail()}`));
      }, this._startTimeoutMs);

      proc.stdin.on('error', () => { /* 終了したワーカーへの書き込み。終了は、'exit'で扱う */ });
      proc.on('error', (error) => {
        settle(reject, new WorkerError(`ワーカーを起動できませんでした（${file}）: ${error.message}`, { cause: error }));
      });

      readline.createInterface({ input: proc.stdout }).on('line', (line) => {
        let message;
        try { message = JSON.parse(line); } catch { return; }   // JSONでない行は、通信の対象外
        if (message === null || typeof message !== 'object' || Array.isArray(message)) return;
        if (message.event === 'ready') { settle(resolve); return; }
        if (typeof message.id === 'number') {
          const pending = this._pending.get(message.id);
          if (pending) { this._pending.delete(message.id); pending.resolve(message); }
        }
      });

      readline.createInterface({ input: proc.stderr }).on('line', (line) => {
        this._stderr.push(line);
        if (this._stderr.length > STDERR_TAIL_LINES) this._stderr.shift();
      });

      proc.on('exit', (code, signal) => {
        const detail = code !== null ? `終了コード ${code}` : `シグナル ${signal}`;
        const error = new WorkerError(`ワーカーが終了しました（${detail}）。${this._tail()}`);
        settle(reject, error);
        // 別のワーカーへ起動し直した後に、古いワーカーの終了が届いた場合は、今のワーカーの依頼を巻き込まない
        if (this._proc === proc) {
          for (const pending of this._pending.values()) pending.reject(error);
          this._pending.clear();
          this._proc = null;
        }
      });
    });
  }

  /**
   * ワーカーを終了させ、切り離す。終了は非同期のため、切り離さないと、次の依頼が、終了しかけのワーカーへ
   * 送られてしまう。切り離した後は、次の依頼が、新しいワーカーを起動する。
   */
  _discard(proc) {
    if (this._proc === proc) {
      this._proc = null;
      this._ready = null;
    }
    killTree(proc);
  }

  _tail() {
    const tail = this.stderrTail;
    return tail ? `\n--- ワーカーの標準エラー（末尾） ---\n${tail}` : '';
  }
}

/** プロセスと、その子孫（Mermaid用のブラウザ等）を終了させる。 */
function killTree(proc) {
  if (!proc || proc.exitCode !== null) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    } else {
      proc.kill('SIGKILL');
    }
  } catch {
    /* すでに終了している等 */
  }
}

module.exports = { WorkerClient, WorkerError, WorkerProtocolError };
