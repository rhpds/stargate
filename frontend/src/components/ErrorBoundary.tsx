import { Component, type ReactNode, type ErrorInfo } from 'react';
import { Alert, PageSection } from '@patternfly/react-core';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <PageSection>
          <Alert variant="danger" title="Something went wrong">
            {this.state.error?.message}
          </Alert>
        </PageSection>
      );
    }
    return this.props.children;
  }
}
