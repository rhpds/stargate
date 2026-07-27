import React, { useState } from 'react';
import { api } from '../api/client';

interface Props {
  text: string;
  namespace?: string;
  cluster?: string;
}

function RunButton({ cmd, namespace, cluster }: { cmd: string; namespace: string; cluster: string }) {
  const [result, setResult] = useState<{ output: string; exit_code: number; loading?: boolean } | null>(null);

  return (
    <div className="my-1" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-2">
        <pre className="flex-1 bg-[#0d0d0d] border border-[#333] rounded px-3 py-1.5 text-xs text-[#4EC9B0] font-mono overflow-x-auto">{cmd}</pre>
        <button
          className="bg-[#333] hover:bg-[#444] text-white text-xs px-3 py-1.5 rounded transition disabled:opacity-50 shrink-0"
          disabled={result?.loading}
          onClick={() => {
            setResult({ output: '', exit_code: 0, loading: true });
            api.runDiagnostic({ command: cmd, namespace, cluster })
              .then((data) => setResult({ output: data.output, exit_code: data.exit_code }))
              .catch((err) => setResult({ output: `Error: ${err.message}`, exit_code: -1 }));
          }}
        >
          {result?.loading ? 'Running...' : result ? 'Re-run' : 'Run'}
        </button>
      </div>
      {result && !result.loading && (
        <pre className={`mt-1 text-xs rounded px-3 py-2 font-mono overflow-x-auto max-h-64 overflow-y-auto ${
          result.exit_code === 0 ? 'bg-[#0d1f0d] text-[#4ade80] border border-[#1a3a1a]' : 'bg-[#1f0d0d] text-[#f87171] border border-[#3a1a1a]'
        }`}>{result.output || '(no output)'}</pre>
      )}
    </div>
  );
}

function extractOcCommand(text: string): string | null {
  const trimmed = text.trim();
  // Match oc command anywhere in the line, stop at natural boundaries
  const match = trimmed.match(/(?:^|Run |Command: |run )(oc\s+(?:get|describe|logs|status|version|api-resources)\s+[^\s](?:[^\s]*(?:\s+(?!to\s|for\s|and\s|if\s|should\s|will\s|that\s|which\s|the\s|this\s|is\s|are\s|was\s|has\s|have\s|can\s|may\s|must\s|could\s|would\s|after\s|before\s|then\s|when\s|where\s)[^\s]+)*))/i);
  if (match?.[1]) return match[1].replace(/[.,;:!?)]+$/, '').trim();
  return null;
}

export default function FormattedAnalysis({ text, namespace, cluster }: Props) {
  if (!text) return null;

  const lines = text.split('\n');
  const elements: React.ReactElement[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let codeKey = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();

    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        const codeText = codeLines.join('\n');
        const ocCmd = extractOcCommand(codeText);
        if (ocCmd && namespace && cluster) {
          elements.push(<RunButton key={`code-${codeKey++}`} cmd={ocCmd} namespace={namespace} cluster={cluster} />);
        } else {
          elements.push(
            <pre key={`code-${codeKey++}`} className="bg-[#0d0d0d] border border-[#333] rounded p-3 text-xs text-[#4EC9B0] overflow-x-auto my-2 font-mono">
              {codeText}
            </pre>
          );
        }
        codeLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    // Numbered header
    if (/^\d+\.\s+[A-Z]/.test(trimmed) || /^##\s+/.test(trimmed)) {
      elements.push(
        <h3 key={i} className="text-white font-bold text-sm mt-4 mb-1 border-b border-[#333] pb-1">
          {formatInline(trimmed.replace(/^##\s+/, ''))}
        </h3>
      );
      continue;
    }

    // Sub-header
    if (/^[a-z]\.\s/.test(trimmed)) {
      elements.push(
        <div key={i} className="text-white text-sm font-medium mt-2 mb-0.5 ml-2">
          {formatInline(trimmed)}
        </div>
      );
      continue;
    }

    // Inline oc command (not in a code block but on its own line)
    const inlineCmd = extractOcCommand(trimmed);
    if (inlineCmd && namespace && cluster) {
      elements.push(<RunButton key={i} cmd={inlineCmd} namespace={namespace} cluster={cluster} />);
      continue;
    }

    // Bullet point
    if (/^\s*[-*•]\s/.test(line)) {
      const indent = line.search(/\S/);
      const bulletText = trimmed.replace(/^[-*•]\s*/, '');
      const bulletCmd = extractOcCommand(bulletText);
      if (bulletCmd && namespace && cluster) {
        elements.push(
          <div key={i} style={{ paddingLeft: `${Math.max(indent * 4, 12)}px` }}>
            <RunButton cmd={bulletCmd} namespace={namespace} cluster={cluster} />
          </div>
        );
        continue;
      }
      elements.push(
        <div key={i} className="text-[#C9C9C9] text-sm" style={{ paddingLeft: `${Math.max(indent * 4, 12)}px` }}>
          <span className="text-[#6A6E73] mr-1">•</span>
          {formatInline(bulletText)}
        </div>
      );
      continue;
    }

    if (!trimmed) {
      elements.push(<div key={i} className="h-2" />);
      continue;
    }

    elements.push(
      <div key={i} className="text-[#C9C9C9] text-sm leading-relaxed">
        {formatInline(trimmed)}
      </div>
    );
  }

  if (inCodeBlock && codeLines.length > 0) {
    const codeText = codeLines.join('\n');
    const ocCmd = extractOcCommand(codeText);
    if (ocCmd && namespace && cluster) {
      elements.push(<RunButton key={`code-${codeKey}`} cmd={ocCmd} namespace={namespace} cluster={cluster} />);
    } else {
      elements.push(
        <pre key={`code-${codeKey}`} className="bg-[#0d0d0d] border border-[#333] rounded p-3 text-xs text-[#4EC9B0] overflow-x-auto my-2 font-mono">
          {codeText}
        </pre>
      );
    }
  }

  return <div className="space-y-0.5">{elements}</div>;
}

function formatInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    const codeMatch = remaining.match(/`([^`]+)`/);
    const boldMatch = remaining.match(/\*\*([^*]+)\*\*/);

    const firstMatch = [codeMatch, boldMatch]
      .filter(Boolean)
      .sort((a, b) => (a!.index ?? Infinity) - (b!.index ?? Infinity))[0];

    if (!firstMatch || firstMatch.index === undefined) {
      parts.push(remaining);
      break;
    }

    if (firstMatch.index > 0) {
      parts.push(remaining.substring(0, firstMatch.index));
    }

    if (firstMatch === codeMatch) {
      parts.push(
        <code key={key++} className="bg-[#2a2a2a] text-[#4EC9B0] px-1 py-0.5 rounded text-xs font-mono">
          {firstMatch[1]}
        </code>
      );
    } else {
      parts.push(
        <strong key={key++} className="text-white font-semibold">{firstMatch[1]}</strong>
      );
    }

    remaining = remaining.substring(firstMatch.index + firstMatch[0].length);
  }

  return <>{parts}</>;
}
