import { Component, type ErrorInfo, type ReactNode } from 'react';

interface WorkspaceErrorBoundaryProps {
  /** Short heading shown instead of the part that failed. */
  title: string;
  /** One or two plain sentences saying what to do next. */
  message: string;
  /** Label of the recovery button. */
  actionLabel: string;
  /** Called when the recovery button is pressed; the boundary then retries. */
  onAction: () => void;
  /** Optional second button, for example a way back to the start page. */
  secondaryLabel?: string;
  onSecondaryAction?: () => void;
  /**
   * When this value changes after a failure the boundary retries by itself,
   * so correcting the input that caused the failure brings the view back.
   */
  retryKey?: unknown;
  className?: string;
  children: ReactNode;
}

interface WorkspaceErrorBoundaryState {
  failed: boolean;
}

/**
 * Keeps a render or effect error inside one part of a workspace. Without a
 * boundary React removes the whole application, which leaves a blank page
 * with no way back.
 */
export class WorkspaceErrorBoundary extends Component<
  WorkspaceErrorBoundaryProps,
  WorkspaceErrorBoundaryState
> {
  state: WorkspaceErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): WorkspaceErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('A workspace view failed to draw.', error, info.componentStack);
  }

  componentDidUpdate(previous: WorkspaceErrorBoundaryProps): void {
    if (this.state.failed && previous.retryKey !== this.props.retryKey) {
      this.setState({ failed: false });
    }
  }

  private recover = (): void => {
    this.props.onAction();
    this.setState({ failed: false });
  };

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    const { title, message, actionLabel, secondaryLabel, onSecondaryAction, className } = this.props;
    return (
      <div
        className={`workspace-error-boundary${className ? ` ${className}` : ''}`}
        role="alert"
        data-testid="workspace-error-boundary"
      >
        <strong>{title}</strong>
        <p>{message}</p>
        <div className="workspace-error-boundary-actions">
          <button type="button" onClick={this.recover}>{actionLabel}</button>
          {secondaryLabel && onSecondaryAction && (
            <button type="button" onClick={onSecondaryAction}>{secondaryLabel}</button>
          )}
        </div>
      </div>
    );
  }
}
