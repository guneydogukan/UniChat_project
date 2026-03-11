/**
 * UniChat Frontend — useChat Hook
 * Chat state yönetimi ve mesaj gönderme mantığı.
 */

import { useState, useEffect, useRef } from 'react';
import { sendMessage } from '../services/api';

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  // Auto Scroll
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Mesaj gönderme
  const handleSend = async (text) => {
    if (!text.trim()) return;

    const userMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const data = await sendMessage(text);
      const botMessage = {
        role: 'bot',
        content: data.response || 'Yanıt alınamadı.',
        sources: data.sources || [],
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error('API Error:', error);
      const errorMessage = {
        role: 'bot',
        content: 'Üzgünüm, şu anda sunucuya erişilemiyor. Lütfen daha sonra tekrar deneyiniz.',
        sources: [],
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

  return {
    messages,
    input,
    setInput,
    isLoading,
    messagesEndRef,
    handleSend,
    handleSubmit,
  };
}
