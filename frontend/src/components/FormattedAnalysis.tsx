import React from 'react';

/**
 * Renders LLM analysis text with basic formatting:
 * - Numbered sections (1. 2. 3.) as headers
 * - Code blocks (```) with dark background
 * - Bullet points (- or *) indented
 * - Bold (**text**) highlighted
 */
export default function FormattedAnalysis({ text }: { text: string }) {
  if (!text) return null;

  const lines = text.split('\n');
  const elements: React.ReactElement[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let codeKey = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();

    // Code block toggle
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <pre key={`code-${codeKey++}`} className="bg-[#0d0d0d] border border-[#333] rounded p-3 text-xs text-[#4EC9B0] overflow-x-auto my-2 font-mono">
            {codeLines.join('\n')}
          </pre>
        );
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

    // Numbered header (1. Root Cause, 2. Isolation, etc.)
    if (/^\d+\.\s+[A-Z]/.test(trimmed)) {
      elements.push(
        <h3 key={i} className="text-white font-bold text-sm mt-4 mb-1 border-b border-[#333] pb-1">
          {formatInline(trimmed)}
        </h3>
      );
      continue;
    }

    // Sub-header (a. b. c.)
    if (/^[a-z]\.\s/.test(trimmed)) {
      elements.push(
        <div key={i} className="text-white text-sm font-medium mt-2 mb-0.5 ml-2">
          {formatInline(trimmed)}
        </div>
      );
      continue;
    }

    // Bullet point
    if (/^\s*[-*]\s/.test(line)) {
      const indent = line.search(/\S/);
      elements.push(
        <div key={i} className="text-[#C9C9C9] text-sm" style={{ paddingLeft: `${Math.max(indent * 4, 12)}px` }}>
          <span className="text-[#6A6E73] mr-1">•</span>
          {formatInline(trimmed.replace(/^[-*]\s*/, ''))}
        </div>
      );
      continue;
    }

    // Empty line
    if (!trimmed) {
      elements.push(<div key={i} className="h-2" />);
      continue;
    }

    // Regular text
    elements.push(
      <div key={i} className="text-[#C9C9C9] text-sm leading-relaxed">
        {formatInline(trimmed)}
      </div>
    );
  }

  // Flush unclosed code block
  if (inCodeBlock && codeLines.length > 0) {
    elements.push(
      <pre key={`code-${codeKey}`} className="bg-[#0d0d0d] border border-[#333] rounded p-3 text-xs text-[#4EC9B0] overflow-x-auto my-2 font-mono">
        {codeLines.join('\n')}
      </pre>
    );
  }

  return <div className="space-y-0.5">{elements}</div>;
}

function formatInline(text: string): React.ReactNode {
  // Bold **text** and `code`
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // Inline code
    const codeMatch = remaining.match(/`([^`]+)`/);
    // Bold
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
