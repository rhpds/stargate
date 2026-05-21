import { useState } from 'react';
import { Button, Label, Tooltip } from '@patternfly/react-core';

interface Props {
  proposedClass: string;
  confidence: number | null;
  reviewed: boolean;
  approved: boolean | null;
  proposalId: number;
  reasoning?: string;
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
}

export default function ClassificationBadge({
  proposedClass,
  confidence,
  reviewed,
  approved,
  proposalId,
  reasoning,
  onApprove,
  onReject,
}: Props) {
  const [acted, setActed] = useState<'approved' | 'rejected' | null>(null);

  const confPct = confidence != null ? Math.round(confidence * 100) : null;
  const confColor = confPct != null && confPct >= 80 ? 'green' : confPct != null && confPct >= 60 ? 'orange' : 'grey';

  if (acted === 'approved' || (reviewed && approved)) {
    return (
      <Tooltip content={reasoning || proposedClass}>
        <Label isCompact color="green">AI: {proposedClass} {confPct != null && `(${confPct}%)`}</Label>
      </Tooltip>
    );
  }
  if (acted === 'rejected' || (reviewed && !approved)) {
    return (
      <Tooltip content={reasoning || proposedClass}>
        <Label isCompact color="grey" style={{ textDecoration: 'line-through' }}>AI: {proposedClass}</Label>
      </Tooltip>
    );
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
      <Tooltip content={reasoning || `AI proposes: ${proposedClass}`}>
        <Label isCompact color={confColor}>
          AI: {proposedClass} {confPct != null && `(${confPct}%)`}
        </Label>
      </Tooltip>
      {onApprove && onReject && (
        <>
          <Button
            variant="plain"
            size="sm"
            style={{ padding: '1px 4px', fontSize: '0.7rem' }}
            onClick={() => { onApprove(proposalId); setActed('approved'); }}
          >
            ✓
          </Button>
          <Button
            variant="plain"
            size="sm"
            style={{ padding: '1px 4px', fontSize: '0.7rem' }}
            onClick={() => { onReject(proposalId); setActed('rejected'); }}
          >
            ✗
          </Button>
        </>
      )}
    </span>
  );
}
