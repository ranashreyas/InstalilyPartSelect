"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";

// Agent API runs on port 8001, Database API on port 8000
const AGENT_API_URL = process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8001";

export default function Home() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Hello! I'm your PartSelect assistant. How can I help you find appliance parts today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");

    // Add user message to state
    const newMessages = [...messages, { role: "user", content: userMessage }];
    setMessages(newMessages);

    setIsLoading(true);

    try {
      // Call the backend chat API
      const response = await fetch(`${AGENT_API_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messages: newMessages }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();

      // Add assistant response
      setMessages((prev) => [...prev, data.message]);

    } catch (error) {
      console.error("Chat error:", error);
      // Add error message
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Sorry, I encountered an error: ${error.message}. Please make sure the backend is running.`,
        },
      ]);
    } finally {
      setIsLoading(false);
      // Keep focus on input after sending
      inputRef.current?.focus();
    }
  };

  // Custom components for markdown rendering
  const markdownComponents = {
    // Links - styled and open in new tab
    a: ({ node, ...props }) => (
      <a
        {...props}
        target="_blank"
        rel="noopener noreferrer"
        className="text-teal-600 hover:text-teal-800 underline font-medium"
      />
    ),
    // Bold text
    strong: ({ node, ...props }) => (
      <strong {...props} className="font-semibold" />
    ),
    // Lists
    ul: ({ node, ...props }) => (
      <ul {...props} className="list-disc list-inside my-2 space-y-1" />
    ),
    ol: ({ node, ...props }) => (
      <ol {...props} className="list-decimal list-inside my-2 space-y-1" />
    ),
    li: ({ node, ...props }) => (
      <li {...props} className="ml-2" />
    ),
    // Paragraphs
    p: ({ node, ...props }) => (
      <p {...props} className="mb-2 last:mb-0" />
    ),
    // Code
    code: ({ node, inline, ...props }) => (
      inline ? (
        <code {...props} className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono" />
      ) : (
        <code {...props} className="block bg-gray-100 p-2 rounded text-sm font-mono my-2 overflow-x-auto" />
      )
    ),
    // Headings
    h1: ({ node, ...props }) => (
      <h1 {...props} className="text-xl font-bold mt-3 mb-2" />
    ),
    h2: ({ node, ...props }) => (
      <h2 {...props} className="text-lg font-bold mt-3 mb-2" />
    ),
    h3: ({ node, ...props }) => (
      <h3 {...props} className="text-base font-bold mt-2 mb-1" />
    ),
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-teal-700 text-white py-4 px-6 shadow-md">
        <h1 className="text-xl font-semibold">PartSelect Assistant</h1>
        <p className="text-teal-100 text-sm">Find refrigerator & dishwasher parts</p>
      </header>

      {/* Messages Container */}
      <main className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                message.role === "user"
                  ? "bg-teal-600 text-white rounded-br-md"
                  : "bg-white text-gray-800 shadow-sm border border-gray-200 rounded-bl-md"
              }`}
            >
              {message.role === "assistant" && (
                <div className="text-xs text-teal-600 font-medium mb-1">Assistant</div>
              )}
              {message.role === "assistant" ? (
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown components={markdownComponents}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white text-gray-800 shadow-sm border border-gray-200 rounded-2xl rounded-bl-md px-4 py-3">
              <div className="text-xs text-teal-600 font-medium mb-1">Assistant</div>
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Input Form */}
      <footer className="bg-white border-t border-gray-200 p-4">
        <form onSubmit={handleSubmit} className="flex gap-3 max-w-4xl mx-auto">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about refrigerator or dishwasher parts..."
            className="flex-1 border border-gray-300 rounded-full px-4 py-3 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent text-black placeholder:text-gray-400"
            disabled={isLoading}
            autoFocus
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="bg-teal-600 text-white px-6 py-3 rounded-full font-medium hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </footer>
    </div>
  );
}
