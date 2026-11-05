import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';
import { finishRuntime, writeReceipt } from './performance-lifecycle';

export default class AcceptanceReporter implements Reporter {
  private started = new Date().toISOString();
  private status: FullResult['status'] | 'running' = 'running';
  private tests: unknown[] = [];
  private heartbeat?: ReturnType<typeof setInterval>;

  private save() {
    writeReceipt(resolve('test-results/performance-run.json'), {
      started_utc: this.started, updated_utc: new Date().toISOString(), status: this.status,
      runtime: process.env.COILEM_ACCEPTANCE_RUNTIME, tests: this.tests,
    });
  }
  onBegin() {
    this.save();
    // Retained even if the job is interrupted or the process is killed.
    this.heartbeat = setInterval(() => this.save(), 30_000);
  }
  onTestEnd(test: TestCase, result: TestResult) {
    const id = test.title.split(': ').at(-1)!;
    const root = process.env.COILEM_ACCEPTANCE_RECHECK_DIR ? 'performance-recheck-evidence' : 'performance-evidence';
    const output = resolve('test-results', root, id);
    const attempt = join(output, 'attempt.json');
    const receipt = {
      test: test.title, status: result.status, duration_s: result.duration / 1000,
      completed_utc: new Date().toISOString(), errors: result.errors.map((error) => error.message),
      attempt: existsSync(attempt) ? JSON.parse(readFileSync(attempt, 'utf8')) : null,
    };
    this.tests.push(receipt);
    if (existsSync(output)) writeReceipt(join(output, 'attempt-result.json'), receipt);
    this.save();
  }
  onEnd(result: FullResult) {
    this.status = result.status;
    clearInterval(this.heartbeat);
    this.save();
  }
  async onExit() {
    // Playwright has stopped its webServer before reporter.onExit.
    const runtime = process.env.COILEM_ACCEPTANCE_RUNTIME;
    const removed = runtime ? finishRuntime(runtime, process.env.COILEM_ACCEPTANCE_OWNED_RUNTIME, this.status === 'passed') : false;
    this.save();
    const path = resolve('test-results/performance-run.json');
    writeReceipt(path, { ...JSON.parse(readFileSync(path, 'utf8')), owned_runtime_removed: removed });
  }
}
