/**
 * UniChat Frontend — Ana Uygulama
 * Bileşen orkestratörü.
 */

import { useState, useEffect } from 'react';
import { useChat } from './hooks/useChat';
import Header from './components/Header';
import ChatArea from './components/ChatArea';
import InputBar from './components/InputBar';
import './App.css';

function App() {
  const [isDarkMode, setIsDarkMode] = useState(true);
  const { messages, input, setInput, isLoading, messagesEndRef, handleSend, handleSubmit } = useChat();

  // Dark Mode Toggle
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 transition-colors duration-300 bg-slate-50 dark:bg-zinc-950 font-sans text-slate-800 dark:text-zinc-200">
      {/* Main Chat Container */}
      <div className="w-full max-w-4xl h-[85vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden transition-colors duration-300 bg-white border-slate-200 dark:bg-zinc-900 dark:border-zinc-800 border">
        
        <Header 
          isDarkMode={isDarkMode} 
          onToggleDarkMode={() => setIsDarkMode(!isDarkMode)} 
        />

        <ChatArea
          messages={messages}
          isLoading={isLoading}
          messagesEndRef={messagesEndRef}
          onQuestionClick={handleSend}
        />

        <InputBar
          input={input}
          onInputChange={setInput}
          onSubmit={handleSubmit}
          isLoading={isLoading}
        />

      </div>
    </div>
  );
}

export default App;
