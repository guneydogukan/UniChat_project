/**
 * UniChat Frontend — MessageBubble Bileşeni
 * Kullanıcı ve bot mesaj baloncukları.
 */

import { Bot } from 'lucide-react';

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';

  return (
    <div
      className={`flex gap-4 ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in-up`}
    >
      {/* Bot İkonu */}
      {!isUser && (
        <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 bg-slate-100 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700">
          <Bot className="w-6 h-6 text-slate-600 dark:text-zinc-400" />
        </div>
      )}

      {/* Mesaj Baloncuğu */}
      <div
        className={`p-4 rounded-2xl max-w-[85%] md:max-w-[75%] text-sm md:text-base leading-relaxed shadow-sm
          ${isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : 'bg-slate-100 text-slate-800 dark:bg-zinc-800 dark:text-zinc-200 rounded-bl-none border border-slate-200 dark:border-zinc-700'
          }`}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
      </div>
    </div>
  );
}
