/**
 * UniChat Frontend — LoadingIndicator Bileşeni
 * Bot yazıyor animasyonu.
 */

import { Bot } from 'lucide-react';

export default function LoadingIndicator() {
  return (
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
  );
}
