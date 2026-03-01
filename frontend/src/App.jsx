import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { GraduationCap, Sun, Moon, Send, Bot } from 'lucide-react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(true);
  const messagesEndRef = useRef(null);

  // Dark Mode Toggle Logic
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  // Auto Scroll
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Send Message Logic
  const handleSend = async (text) => {
    if (!text.trim()) return;

    const userMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await axios.post('http://localhost:8000/api/chat', { message: text });
      // Adjust based on actual API response structure. 
      // Assuming { response: "string" } or { message: "string" }
      const botContent = response.data.response || response.data.message || "Yanıt alınamadı.";
      
      const botMessage = { role: 'bot', content: botContent };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error('API Error:', error);
      const errorMessage = { 
        role: 'bot', 
        content: 'Üzgünüm, şu anda sunucuya erişilemiyor. Lütfen daha sonra tekrar deneyiniz.' 
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    handleSend(input);
  };

  const quickQuestions = [
    'Yemekhane kuralları nelerdir?',
    'Bitirme projesi teslim tarihi ne zaman?',
    'Bir dönemde kaç kredi alabilirim?',
    'Yaz okulu başvuruları ne zaman?'
  ];

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 transition-colors duration-300 bg-slate-50 dark:bg-zinc-950 font-sans text-slate-800 dark:text-zinc-200">
      
      {/* Main Chat Container */}
      <div className="w-full max-w-4xl h-[85vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden transition-colors duration-300 bg-white border-slate-200 dark:bg-zinc-900 dark:border-zinc-800 border">
        
        {/* Header */}
        <header className="flex items-center justify-between p-6 border-b border-slate-100 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-100 dark:bg-zinc-800 rounded-lg">
              <GraduationCap className="w-8 h-8 text-slate-800 dark:text-zinc-100" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-slate-800 dark:text-zinc-100 tracking-tight">
                UniChat
              </h1>
              <div className="flex items-center gap-2 mt-1">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                </span>
                <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">
                  Yapay Zeka Asistanı Çevrimiçi
                </span>
              </div>
            </div>
          </div>
          
          <button 
            onClick={() => setIsDarkMode(!isDarkMode)}
            className="p-3 rounded-full hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors text-slate-600 dark:text-zinc-400"
          >
            {isDarkMode ? <Sun className="w-6 h-6" /> : <Moon className="w-6 h-6" />}
          </button>
        </header>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar bg-white dark:bg-zinc-900">
          {messages.length === 0 ? (
            /* Welcome Screen */
            <div className="flex flex-col items-center justify-center h-full space-y-10 animate-fade-in-up">
              <div className="text-center space-y-4">
                <h2 className="text-3xl md:text-4xl font-semibold text-slate-800 dark:text-zinc-100 tracking-tight">
                  Merhaba! Size nasıl yardımcı olabilirim?
                </h2>
                <p className="text-slate-500 dark:text-zinc-400 text-lg">
                  Üniversite ile ilgili merak ettiğiniz her şeyi sorun.
                </p>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-2xl">
                {quickQuestions.map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSend(q)}
                    className="p-4 text-left rounded-xl transition-all border shadow-sm
                      bg-white border-slate-200 hover:bg-slate-50 text-slate-700
                      dark:bg-zinc-900 dark:border-zinc-700 dark:hover:bg-zinc-800 dark:text-zinc-300"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* Message List */
            <>
              {messages.map((msg, idx) => (
                <div 
                  key={idx} 
                  className={`flex gap-4 ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in-up`}
                >
                  {/* Bot Icon */}
                  {msg.role === 'bot' && (
                    <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 bg-slate-100 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700">
                      <Bot className="w-6 h-6 text-slate-600 dark:text-zinc-400" />
                    </div>
                  )}

                  {/* Bubble */}
                  <div className={`p-4 rounded-2xl max-w-[85%] md:max-w-[75%] text-sm md:text-base leading-relaxed shadow-sm
                    ${msg.role === 'user' 
                      ? 'bg-blue-600 text-white rounded-br-none' 
                      : 'bg-slate-100 text-slate-800 dark:bg-zinc-800 dark:text-zinc-200 rounded-bl-none border border-slate-200 dark:border-zinc-700'
                    }`}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}

              {/* Loading Indicator */}
              {isLoading && (
                <div className="flex gap-4 justify-start animate-fade-in-up">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 bg-slate-100 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700">
                    <Bot className="w-6 h-6 text-slate-600 dark:text-zinc-400" />
                  </div>
                  <div className="p-4 rounded-2xl rounded-bl-none bg-slate-100 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full bg-slate-400 dark:bg-zinc-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-2 h-2 rounded-full bg-slate-400 dark:bg-zinc-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-2 h-2 rounded-full bg-slate-400 dark:bg-zinc-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Footer Input Area */}
        <footer className="p-6 bg-white dark:bg-zinc-900 border-t border-slate-100 dark:border-zinc-800">
          <form onSubmit={handleSubmit} className="flex gap-3 mb-6 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Bir mesaj yazın..."
              disabled={isLoading}
              className="flex-1 p-4 rounded-xl border outline-none transition-all
                bg-white border-slate-300 text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500
                dark:bg-zinc-950 dark:border-zinc-700 dark:text-white dark:placeholder-zinc-600 dark:focus:border-zinc-500 dark:focus:ring-zinc-500"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="p-4 rounded-xl transition-all flex items-center justify-center
                bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              <Send className="w-5 h-5" />
            </button>
          </form>
          
          <div className="text-center space-y-1">
            <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 dark:text-zinc-500">
              UNICHAT AI • YAPAY ZEKA ASİSTANI
            </h3>
            <p className="text-[10px] text-slate-400 dark:text-zinc-600">
              Yapay zeka asistanı tarafından verilen yanıtlar her zaman %100 doğru olmayabilir.
            </p>
          </div>
        </footer>

      </div>
    </div>
  );
}

export default App;
