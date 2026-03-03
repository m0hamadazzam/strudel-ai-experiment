import React from 'react';
import { sanitizeReasoningText } from './copilotShared';

const THINKING_SCAN_ANIMATION = 'strudelThinkingScan 1.25s ease-in-out infinite';

export default function CopilotThinkingIndicator({ liveAssistant }) {
    const displayText = liveAssistant?.reasoning?.trim()
        ? sanitizeReasoningText(liveAssistant.reasoning)
        : (liveAssistant?.phase || 'Thinking through the request.');

    return (
        <div className="flex justify-start">
            <div className="max-w-[85%] rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm space-y-3">
                <div className="flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.16em] text-cyan-300/80">
                    <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-cyan-300 animate-pulse" />
                        <span>Thinking</span>
                    </div>
                    {liveAssistant?.isWebSearching && (
                        <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-1 text-[10px] tracking-[0.12em] text-cyan-200/90">
                            Web
                        </span>
                    )}
                </div>

                <div className="relative h-1 overflow-hidden rounded-full bg-white/10">
                    <div
                        className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-gradient-to-r from-transparent via-cyan-300/90 to-transparent"
                        style={{ animation: THINKING_SCAN_ANIMATION }}
                    />
                </div>

                <div className="whitespace-pre-wrap text-sm text-foreground/90">
                    {displayText}
                </div>
            </div>
        </div>
    );
}
