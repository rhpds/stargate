import { Label } from '@patternfly/react-core';

type StatusColor = 'green' | 'orange' | 'red' | 'blue' | 'grey';

function resolveColor(status: string): StatusColor {
  const s = status.toLowerCase();
  if (['healthy', 'pass', 'passed', 'started', 'completed', 'active', 'ready', 'in_development'].includes(s)) return 'green';
  if (['warning', 'warn', 'warned', 'degraded', 'planning', 'pending'].includes(s)) return 'orange';
  if (['critical', 'fail', 'failed', 'error', 'provision-failed', 'crashlooping'].includes(s)) return 'red';
  if (['info', 'unknown'].includes(s)) return 'blue';
  return 'grey';
}

interface StatusLabelProps {
  status: string;
  isCompact?: boolean;
}

export default function StatusLabel({ status, isCompact = false }: StatusLabelProps) {
  return (
    <Label color={resolveColor(status)} isCompact={isCompact}>
      {status}
    </Label>
  );
}
