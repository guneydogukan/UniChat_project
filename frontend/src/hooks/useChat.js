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

      let errorText;
      if (error.code === 'ECONNABORTED') {
        errorText = 'Yanıt süresi çok uzun sürdü. Lütfen daha kısa veya net bir soru sorarak tekrar deneyiniz.';
      } else if (error.response) {
        const detail = error.response.data?.detail;
        errorText = detail || 'Sunucuda bir hata oluştu. Lütfen daha sonra tekrar deneyiniz.';
      } else if (error.request) {
        errorText = 'Sunucuya bağlanılamadı. Lütfen internet bağlantınızı ve sunucunun çalıştığını kontrol ediniz.';
      } else {
        errorText = 'Beklenmeyen bir hata oluştu. Lütfen daha sonra tekrar deneyiniz.';
      }

      const errorMessage = {
        role: 'bot',
        content: errorText,
        sources: [],
        isError: true,
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
