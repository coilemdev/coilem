import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

/** Delete only the runtime this invocation created, after the server exits. */
export function finishRuntime(runtime: string, owned: string | undefined, passed: boolean): boolean {
  if (!passed || !owned || resolve(runtime) !== resolve(owned)) return false;
  const marker = join(runtime, '.acceptance-owned');
  if (!existsSync(marker) || readFileSync(marker, 'utf8') !== owned) return false;
  rmSync(runtime, { recursive: true, maxRetries: 10, retryDelay: 200 });
  return true;
}

export function writeReceipt(path: string, receipt: unknown): void {
  writeFileSync(path, `${JSON.stringify(receipt, null, 2)}\n`);
}
