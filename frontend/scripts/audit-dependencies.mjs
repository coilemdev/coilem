// Audit the locked frontend dependencies.
//
// Fails on any high or critical npm advisory, except advisories listed in
// audit-exceptions.json with a written reason. An exception lapses, and the audit
// fails again, once npm no longer reports the advisory, once a version outside its
// vulnerable range is published, or after its review_by date.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const BLOCKING = new Set(['high', 'critical']);

/** The advisories in an `npm audit --json` report, once each, keyed by their GHSA id. */
export function advisories(report) {
  const found = new Map();
  for (const vulnerability of Object.values(report?.vulnerabilities ?? {})) {
    for (const via of vulnerability.via ?? []) {
      if (typeof via !== 'object' || !via) continue;
      const id = String(via.url ?? via.source ?? '').split('/').pop();
      if (!found.has(id)) found.set(id, { id, package: via.name, severity: via.severity, title: via.title, range: via.range, url: via.url });
    }
  }
  return [...found.values()];
}

function parts(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(String(version).trim());
  if (!match) throw new Error(`not a version: ${version}`);
  return match.slice(1).map(Number);
}

/** -1, 0 or 1, comparing major.minor.patch. */
export function compareVersions(left, right) {
  const [a, b] = [parts(left), parts(right)];
  for (let index = 0; index < 3; index += 1) if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  return 0;
}

/** Whether `version` is inside an upper-bounded range such as "<=4.0.7" or "<4.0.8". */
export function insideRange(version, range) {
  const match = /^\s*(<=|<)\s*(\S+)\s*$/.exec(range);
  if (!match) throw new Error(`unsupported vulnerable_range ${JSON.stringify(range)}: use "<=x.y.z" or "<x.y.z"`);
  const order = compareVersions(version, match[2]);
  return match[1] === '<=' ? order <= 0 : order < 0;
}

/**
 * The audit's verdict. `latest` maps each excepted package to its newest published
 * version; `today` is an ISO date (YYYY-MM-DD).
 */
export function evaluateAudit({ report, exceptions, latest, today }) {
  const found = advisories(report);
  const failures = [];
  const accepted = [];
  for (const advisory of found.filter(item => BLOCKING.has(item.severity))) {
    if (!exceptions.some(exception => exception.id === advisory.id)) {
      failures.push(`${advisory.id} (${advisory.package}, ${advisory.severity}): ${advisory.title} ${advisory.url ?? ''}`.trim()
        + '. Update the dependency, or review it and add it to audit-exceptions.json with a reason.');
    }
  }
  for (const exception of exceptions) {
    const reported = found.find(item => item.id === exception.id);
    if (!reported) {
      failures.push(`${exception.id} is no longer reported by npm audit: remove its exception from audit-exceptions.json.`);
    } else if (exception.review_by < today) {
      failures.push(`${exception.id} (${exception.package}) passed its review date ${exception.review_by}: review it again.`);
    } else if (latest[exception.package] && !insideRange(latest[exception.package], exception.vulnerable_range)) {
      failures.push(`${exception.package} ${latest[exception.package]} is published, outside ${exception.id}'s vulnerable range `
        + `${exception.vulnerable_range}: update the lock to it and remove the exception.`);
    } else {
      accepted.push({ ...exception, title: reported.title });
    }
  }
  return { failures, accepted };
}

function npm(args) {
  return spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

function main() {
  const exceptions = JSON.parse(readFileSync(new URL('../audit-exceptions.json', import.meta.url), 'utf8')).exceptions;
  const audit = npm(['audit', '--json']);
  let report;
  try {
    report = JSON.parse(audit.stdout);
  } catch {
    console.error(`npm audit did not return a report (exit ${audit.status}):\n${audit.stderr || audit.stdout}`);
    return 1;
  }
  if (report.error) {
    console.error(`npm audit failed: ${JSON.stringify(report.error)}`);
    return 1;
  }
  const latest = {};
  for (const exception of exceptions) {
    const view = npm(['view', exception.package, 'version']);
    if (view.status !== 0) {
      console.error(`Could not read the latest ${exception.package} version:\n${view.stderr}`);
      return 1;
    }
    latest[exception.package] = view.stdout.trim();
  }
  const { failures, accepted } = evaluateAudit({ report, exceptions, latest, today: new Date().toISOString().slice(0, 10) });
  for (const item of accepted) {
    console.log(`Accepted ${item.id} (${item.package} ${item.vulnerable_range}, latest ${latest[item.package]}), review by ${item.review_by}: ${item.reason}`);
  }
  if (failures.length) {
    console.error(`Frontend dependency audit failed:\n- ${failures.join('\n- ')}`);
    return 1;
  }
  const counts = report.metadata?.vulnerabilities ?? {};
  console.log(`Frontend dependency audit passed: no unreviewed high or critical advisories (${counts.total ?? 0} reported in all).`);
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) process.exitCode = main();
