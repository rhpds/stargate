import { useState } from 'react';
import { useRecommendationFeedback, useLLMFeedback } from '../api/hooks';

interface IssueFeedbackProps {
  namespace: string;
  cluster: string;
  failure_class: string;
}

export function IssueFeedbackPanel({ namespace, cluster, failure_class }: IssueFeedbackProps) {
  const [expanded, setExpanded] = useState(false);
  const [classCorrect, setClassCorrect] = useState<boolean | null>(null);
  const [correctedClass, setCorrectedClass] = useState('');
  const [isFalsePositive, setIsFalsePositive] = useState(false);
  const [dismissNote, setDismissNote] = useState('');
  const [notes, setNotes] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const feedback = useRecommendationFeedback();

  const handleSubmit = (e: React.MouseEvent) => {
    e.stopPropagation();
    feedback.mutate(
      {
        namespace,
        cluster,
        failure_class,
        correct_classification: classCorrect ?? undefined,
        corrected_class: classCorrect === false ? correctedClass || undefined : undefined,
        false_positive: isFalsePositive || undefined,
        dismiss_note: isFalsePositive ? dismissNote || undefined : undefined,
        notes: notes || undefined,
      },
      { onSuccess: () => setSubmitted(true) },
    );
  };

  if (submitted) {
    return (
      <div className="border-t border-[#333] pt-2 mt-2">
        <span className="text-[#3E8635] text-xs font-medium">Feedback recorded</span>
      </div>
    );
  }

  return (
    <div className="border-t border-[#333] pt-2 mt-2" onClick={(e) => e.stopPropagation()}>
      <button
        className="text-[#6A6E73] text-xs hover:text-white transition flex items-center gap-1"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-[10px]">{expanded ? '▼' : '▶'}</span>
        Leave feedback on this finding
      </button>

      {expanded && (
        <div className="mt-2 space-y-3">
          <div className="space-y-1">
            <span className="text-[#6A6E73] text-xs">Classification correct?</span>
            <div className="flex gap-2 mt-1">
              <button
                className={`w-7 h-7 rounded border flex items-center justify-center text-sm transition ${
                  classCorrect === true
                    ? 'border-[#3E8635] bg-[#3E8635]/20 text-[#3E8635]'
                    : 'border-[#333] text-[#6A6E73] hover:border-[#555]'
                }`}
                onClick={() => setClassCorrect(classCorrect === true ? null : true)}
              >
                {'\u{1F44D}'}
              </button>
              <button
                className={`w-7 h-7 rounded border flex items-center justify-center text-sm transition ${
                  classCorrect === false
                    ? 'border-[#C9190B] bg-[#C9190B]/20 text-[#C9190B]'
                    : 'border-[#333] text-[#6A6E73] hover:border-[#555]'
                }`}
                onClick={() => setClassCorrect(classCorrect === false ? null : false)}
              >
                {'\u{1F44E}'}
              </button>
            </div>
            {classCorrect === false && (
              <input
                className="mt-1 w-full bg-[#151515] border border-[#333] rounded px-2 py-1 text-sm text-white placeholder-[#6A6E73] focus:outline-none focus:border-[#555]"
                placeholder="Correct class..."
                value={correctedClass}
                onChange={(e) => setCorrectedClass(e.target.value)}
              />
            )}
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isFalsePositive}
              onChange={(e) => setIsFalsePositive(e.target.checked)}
              className="accent-[#EE0000]"
            />
            <span className="text-xs text-[#8A8D90]">Not a real issue</span>
          </label>
          {isFalsePositive && (
            <input
              className="w-full bg-[#151515] border border-[#333] rounded px-2 py-1 text-sm text-white placeholder-[#6A6E73] focus:outline-none focus:border-[#555]"
              placeholder="Why not? (optional)"
              value={dismissNote}
              onChange={(e) => setDismissNote(e.target.value)}
            />
          )}

          <textarea
            className="w-full bg-[#151515] border border-[#333] rounded px-2 py-1 text-sm text-white placeholder-[#6A6E73] focus:outline-none focus:border-[#555] resize-none"
            rows={2}
            placeholder="Add a note..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />

          <button
            className="bg-[#333] hover:bg-[#444] text-white text-xs font-medium px-3 py-1.5 rounded transition disabled:opacity-50"
            disabled={feedback.isPending}
            onClick={handleSubmit}
          >
            {feedback.isPending ? 'Submitting...' : 'Submit Feedback'}
          </button>
          {feedback.isError && (
            <span className="text-[#C9190B] text-xs ml-2">Failed to submit</span>
          )}
        </div>
      )}
    </div>
  );
}

interface AiAnalysisFeedbackProps {
  llmMetricId?: number;
}

export function AiAnalysisFeedback({ llmMetricId }: AiAnalysisFeedbackProps) {
  const [helpful, setHelpful] = useState<boolean | null>(null);
  const [notes, setNotes] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const feedback = useLLMFeedback();

  const handleSubmit = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (helpful === null) return;
    feedback.mutate(
      {
        llm_metric_id: llmMetricId,
        endpoint: 'remediation',
        helpful,
        notes: notes || undefined,
      },
      { onSuccess: () => setSubmitted(true) },
    );
  };

  if (submitted) {
    return (
      <div className="border-t border-[#2e2e2e] pt-2 mt-3">
        <span className="text-[#3E8635] text-xs font-medium">Thanks for your feedback</span>
      </div>
    );
  }

  return (
    <div className="border-t border-[#2e2e2e] pt-2 mt-3" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-3">
        <span className="text-[#6A6E73] text-xs">Was this helpful?</span>
        <button
          className={`w-7 h-7 rounded border flex items-center justify-center text-sm transition ${
            helpful === true
              ? 'border-[#3E8635] bg-[#3E8635]/20 text-[#3E8635]'
              : 'border-[#333] text-[#6A6E73] hover:border-[#555]'
          }`}
          onClick={() => setHelpful(helpful === true ? null : true)}
        >
          {'\u{1F44D}'}
        </button>
        <button
          className={`w-7 h-7 rounded border flex items-center justify-center text-sm transition ${
            helpful === false
              ? 'border-[#C9190B] bg-[#C9190B]/20 text-[#C9190B]'
              : 'border-[#333] text-[#6A6E73] hover:border-[#555]'
          }`}
          onClick={() => setHelpful(helpful === false ? null : false)}
        >
          {'\u{1F44E}'}
        </button>
      </div>

      {helpful === false && (
        <input
          className="mt-2 w-full bg-[#0d0d0d] border border-[#333] rounded px-2 py-1 text-sm text-white placeholder-[#6A6E73] focus:outline-none focus:border-[#555]"
          placeholder="What was wrong or missing?"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      )}

      {helpful !== null && (
        <button
          className="mt-2 bg-[#333] hover:bg-[#444] text-white text-xs font-medium px-3 py-1.5 rounded transition disabled:opacity-50"
          disabled={feedback.isPending}
          onClick={handleSubmit}
        >
          {feedback.isPending ? 'Submitting...' : 'Submit'}
        </button>
      )}
      {feedback.isError && (
        <span className="text-[#C9190B] text-xs ml-2">Failed to submit</span>
      )}
    </div>
  );
}
