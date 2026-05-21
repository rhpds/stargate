import { render, screen } from '@testing-library/react';
import StatusLabel from '../../components/StatusLabel';

describe('StatusLabel', () => {
  it('renders healthy status in green', () => {
    render(<StatusLabel status="healthy" />);
    expect(screen.getByText('healthy')).toBeInTheDocument();
  });

  it('renders failed status in red', () => {
    render(<StatusLabel status="failed" />);
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('renders warning status', () => {
    render(<StatusLabel status="warning" />);
    expect(screen.getByText('warning')).toBeInTheDocument();
  });

  it('renders compact variant', () => {
    render(<StatusLabel status="pass" isCompact />);
    expect(screen.getByText('pass')).toBeInTheDocument();
  });

  it('renders unknown status in grey', () => {
    render(<StatusLabel status="something_else" />);
    expect(screen.getByText('something_else')).toBeInTheDocument();
  });
});
