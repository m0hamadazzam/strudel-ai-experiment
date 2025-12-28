import { useState } from 'react';

export default function AICopilotSidebar() {
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([]);

    const handleInputChange = (e) => {
        setInput(e.target.value);
    };

    const handleSend = () => {
        const text = input.trim();
        if (!text) return;

        const userMsg = { role: 'user', content: text };
        const botMsg = {
            role: 'assistant',
            content: 'Got it. (stub) What do you want to change?'
        };

        setMessages((prev) => [...prev, userMsg, botMsg]);
        setInput('');
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
                                    text-sm ${isUser ?
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

            <div className="flex gap-2">
                <input
                    value={input}
                    onChange={handleInputChange}
                    className="flex-1 bg-black/30 text-foreground border border-white/10 rounded px-2 py-1 text-sm outline-none placeholder:text-foreground/40"
                    placeholder="Describe what you want…"
                />
                <button
                    onClick={handleSend}
                    className="px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-sm"
                >
                    Send
                </button>
            </div>
        </aside>
    );
}
