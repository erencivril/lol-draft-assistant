import { Component, type ErrorInfo, Fragment, type ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
  resetKey: number;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = {
    hasError: false,
    resetKey: 0,
  };

  static getDerivedStateFromError(): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("UI render failed", error, errorInfo);
  }

  private handleRetry = () => {
    this.setState((state) => ({
      hasError: false,
      resetKey: state.resetKey + 1,
    }));
  };

  override render() {
    if (this.state.hasError) {
      return (
        <main className="app-shell">
          <section className="panel glass error-boundary">
            <p className="phase-pill">Unexpected UI issue</p>
            <h1>Draft board crashed while rendering.</h1>
            <p className="muted">The backend can keep running, and you can retry the interface without losing local data.</p>
            <button className="button-primary" type="button" onClick={this.handleRetry}>
              Try again
            </button>
          </section>
        </main>
      );
    }

    return <Fragment key={this.state.resetKey}>{this.props.children}</Fragment>;
  }
}
