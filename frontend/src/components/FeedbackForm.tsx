import { useState } from 'react';
import {
  ActionGroup,
  Alert,
  Button,
  Checkbox,
  Form,
  FormGroup,
  TextArea,
  TextInput,
} from '@patternfly/react-core';
import { useFeedback } from '../api/hooks';

interface Props {
  runId: string;
  currentClass: string | null;
}

export default function FeedbackForm({ runId, currentClass }: Props) {
  const [correct, setCorrect] = useState(true);
  const [correctedClass, setCorrectedClass] = useState('');
  const [notes, setNotes] = useState('');
  const feedback = useFeedback();

  if (feedback.isSuccess) {
    return <Alert variant="success" title="Feedback submitted" isInline isPlain style={{ marginTop: '1rem' }} />;
  }

  return (
    <div style={{ marginTop: '1rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>Ops Feedback</h4>
      <Form isHorizontal>
        <FormGroup label="Classification correct?" fieldId="correct">
          <Checkbox
            id="correct"
            isChecked={correct}
            onChange={(_e, checked) => setCorrect(checked)}
            label={currentClass ? `"${currentClass}" is correct` : 'Classification is correct'}
          />
        </FormGroup>
        {!correct && (
          <FormGroup label="Correct class" fieldId="corrected-class">
            <TextInput id="corrected-class" value={correctedClass} onChange={(_e, val) => setCorrectedClass(val)} placeholder="e.g. pods_crashlooping" />
          </FormGroup>
        )}
        <FormGroup label="Notes" fieldId="notes">
          <TextArea id="notes" value={notes} onChange={(_e, val) => setNotes(val)} rows={2} placeholder="Optional notes for the team" />
        </FormGroup>
        <ActionGroup>
          <Button
            variant="primary"
            size="sm"
            isLoading={feedback.isPending}
            isDisabled={feedback.isPending}
            onClick={() => feedback.mutate({
              runId,
              body: {
                correct_classification: correct,
                corrected_class: !correct && correctedClass ? correctedClass : undefined,
                notes: notes || undefined,
                reviewed_by: 'ops-user',
              },
            })}
          >
            Submit Feedback
          </Button>
        </ActionGroup>
        {feedback.isError && <Alert variant="danger" title="Failed to submit feedback" isInline isPlain />}
      </Form>
    </div>
  );
}
