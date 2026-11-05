import type { ReactNode } from 'react';

/** Shared page frame for editable motors and frozen published references. */
export function MotorWorkflowShell({ topBar, children }: { topBar: ReactNode; children: ReactNode }) {
  return <div className="public-coilem-shell">{topBar}
    <main className="workflow-stage-shell"><div className="workflow-stage-content">{children}</div></main>
  </div>;
}
