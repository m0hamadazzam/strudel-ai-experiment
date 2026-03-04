import React from 'react';

/**
 * Multiline text input for sending prompts to the AI Copilot.
 *
 * This component keeps the layout concerns (auto‑resizing, send button, disabled
 * state) separate from business logic, which is handled by the parent sidebar.
 *
 * @param {object} props
 * @param {string} props.input - Current value of the prompt textarea.
 * @param {boolean} props.isLoading - Whether a request is currently in flight.
 * @param {string} props.placeholder - Short hint text shown when the input is empty.
 * @param {React.RefObject<HTMLTextAreaElement>} props.textareaRef - Ref used for auto‑resizing logic.
 * @param {(event: React.ChangeEvent<HTMLTextAreaElement>) => void} props.onChange - Change handler for the textarea.
 * @param {(event: React.KeyboardEvent<HTMLTextAreaElement>) => void} props.onKeyDown - Key handler, typically to submit on Enter.
 * @param {() => void} props.onSend - Callback invoked when the user presses the send button.
 */
export default function CopilotInput({
    input,
    isLoading,
    placeholder,
    textareaRef,
    onChange,
    onKeyDown,
    onSend,
}) {
    return (
        <div className="relative">
            <textarea
                ref={textareaRef}
                value={input}
                onChange={onChange}
                onKeyDown={onKeyDown}
                rows={1}
                className="
                w-full resize-none bg-black/30 text-foreground border
                border-white/10 rounded-2xl px-4 pt-3 pb-3 pr-12
                text-sm outline-none placeholder:text-foreground/40
                overflow-hidden max-h-40
            "
                placeholder={placeholder}
            />

            <button
                onClick={onSend}
                disabled={!input.trim() || isLoading}
                className="
                absolute right-2 bottom-3 h-8 w-8 rounded-full
                bg-white text-black disabled:opacity-40
                disabled:cursor-not-allowed flex items-center
                justify-center
            "
                aria-label="Send"
                title="Send"
            >
                <svg
                    viewBox="0 0 24 24"
                    className="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                >
                    <path d="M12 19V5" />
                    <path d="M5 12l7-7 7 7" />
                </svg>
            </button>
        </div>
    );
}
