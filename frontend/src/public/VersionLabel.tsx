import { useEffect, useRef, useState } from 'react';
import { getPublicHealth, getUpdateStatus, startUpgradeAndRestart, type UpdateStatus } from './api';
import { Popover } from './Popover';

const RESTART_POLL_MS = 2000;
const RESTART_TIMEOUT_MS = 20 * 60 * 1000;

/**
 * The version beside the logo. It reads the result of the local backend's
 * daily update check and shows an **Update** tag when a newer coilEM is
 * released. Where the launcher can do it, **Upgrade and restart** upgrades
 * coilEM in place; elsewhere the tag gives the command. What the check sends
 * and how to turn it off are in the README, not here.
 * The browser never contacts coilem.com itself: the backend does, and this
 * only reads `/updates`.
 */
export function VersionLabel({ version }: { version: string | null | undefined }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [upgrade, setUpgrade] = useState<'idle' | 'restarting' | 'lost'>('idle');
  const [refused, setRefused] = useState<string | null>(null);
  const restartTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!version) return undefined;
    let current = true;
    // The first read may start the day's check; the second shows its answer.
    const read = () => getUpdateStatus().then((next) => { if (current) setStatus(next); }).catch(() => undefined);
    void read();
    const again = window.setTimeout(read, 8000);
    return () => { current = false; window.clearTimeout(again); };
  }, [version]);

  useEffect(() => () => { if (restartTimer.current !== null) window.clearTimeout(restartTimer.current); }, []);

  if (!version) return null;
  const latest = status?.latest ?? null;
  const failed = status?.last_upgrade && !status.last_upgrade.ok ? status.last_upgrade : null;

  // coilEM stops, upgrades and comes back on the same port. Once it has been
  // away and answers again, reload: the page must run the new version's code,
  // and after a failed upgrade the reloaded menu says what went wrong.
  const waitForRestart = (startedAt: number, wasAway: boolean) => {
    restartTimer.current = window.setTimeout(() => {
      getPublicHealth()
        .then(() => {
          if (wasAway) window.location.reload();
          else waitForRestart(startedAt, false);
        })
        .catch(() => {
          if (Date.now() - startedAt > RESTART_TIMEOUT_MS) setUpgrade('lost');
          else waitForRestart(startedAt, true);
        });
    }, RESTART_POLL_MS);
  };
  const startUpgrade = () => {
    setRefused(null);
    setUpgrade('restarting');
    startUpgradeAndRestart()
      .then(() => waitForRestart(Date.now(), false))
      .catch((error: unknown) => {
        setUpgrade('idle');
        // The API client rejects with `{ message }`; a network failure with an Error.
        const message = (error as { message?: unknown } | null)?.message;
        setRefused(typeof message === 'string' && message && !(error instanceof Error) ? message : 'coilEM could not start the upgrade.');
      });
  };

  return (
    <div className="version-label">
      <span className="logo-version">v{version}</span>
      {latest && (
        <Popover
          className="version-update"
          trigger={(props) => (
            <button type="button" className="logo-version-update" aria-label={`Version ${latest} is available`} {...props}>
              {upgrade === 'restarting' ? 'Upgrading' : 'Update'}
            </button>
          )}
        >
          {upgrade === 'restarting' ? (
            <p role="status"><strong>Upgrading to coilEM {latest}…</strong></p>
          ) : upgrade === 'lost' ? (
            <p role="alert"><strong>coilEM has not come back.</strong> Look at the terminal it runs in, then start it again with <code>coilem</code>.</p>
          ) : (
            <>
              <p><strong>coilEM {latest} is available.</strong></p>
              {failed && <p role="alert" className="version-label-failed"><strong>The upgrade did not finish.</strong> {failed.message} To upgrade by hand, stop coilEM and run <code>{failed.manual}</code>.</p>}
              {status?.self_upgrade ? (
                <button type="button" className="version-label-upgrade" onClick={startUpgrade}>{failed ? 'Try again' : 'Upgrade and restart'}</button>
              ) : !failed && (
                <>
                  <p>Stop coilEM, then run <code>{status?.upgrade_command}</code> and start it again.</p>
                  <p className="version-label-note">If you start it with uvx, run <code>uvx coilem@latest</code> instead.</p>
                </>
              )}
              {refused && <p role="alert" className="version-label-failed">{refused}</p>}
            </>
          )}
        </Popover>
      )}
    </div>
  );
}
