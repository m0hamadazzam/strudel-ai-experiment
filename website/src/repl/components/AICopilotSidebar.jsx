import { useRef, useState } from 'react';

export default function AICopilotSidebar() {
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([]);
    const textareaRef = useRef(null);

    const autoResizeTextarea = () => {
        const el = textareaRef.current;
        if (!el) return;

        el.style.height = 'auto';

        const next = el.scrollHeight;
        const max = 160; // matches Tailwind max-h-40 (~160px)

        el.style.height = `${Math.min(next, max)}px`;
        el.style.overflowY = next > max ? 'auto' : 'hidden';
    };



    const handleInputChange = (e) => {
        setInput(e.target.value);
        requestAnimationFrame(autoResizeTextarea);
    };

    const handleSend = () => {
        const text = input.trimEnd();
        if (!text.trim()) return;

        const userMsg = { role: 'user', content: text };
        const botMsg = {
            role: 'assistant',
            content: 'Got it. (stub) What do you want to change?'
        };

        setMessages((prev) => [...prev, userMsg, botMsg]);
        setInput('');

        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (!el) return;
            el.style.height = 'auto';
            el.style.overflowY = 'hidden';
        });

    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };


    return (
        <aside className="w-[360px] h-full border-l border-white/10 bg-background text-foreground overflow-auto p-3">
            <div className="font-bold mb-2">AI Copilot</div>

            <div className="mb-3 space-y-2">
                {messages.map((msg, index) => {
                    const isUser = msg.role === 'user';

                    return (
                        <div
                            key={index}
                            className={
                                `flex ${isUser ?
                                    'justify-end' : 'justify-start'}`
                            }
                        >
                            <div
                                className={
                                    `max-w-[85%] rounded px-2 py-1 
                                    text-sm whitespace-pre-wrap ${isUser ?
                                        'bg-white/10' : 'bg-background'
                                    }`
                                }
                            >
                                {msg.content}
                            </div>
                        </div>
                    );
                })}


            </div>
            <div className="relative">
                <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    rows={1}
                    className="
                        w-full resize-none bg-black/30 text-foreground border
                        border-white/10 rounded-2xl px-4 pt-3 pb-3 pr-12
                        text-sm outline-none placeholder:text-foreground/40
                        overflow-hidden max-h-40
                    "
                    placeholder="Describe what you want…"
                />

                <button
                    onClick={handleSend}
                    disabled={!input.trim()}
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


        </aside>
    );
}
