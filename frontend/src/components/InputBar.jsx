/**
 * UniChat Frontend — InputBar Bileşeni
 * Mesaj giriş formu ve footer.
 */

import { Send } from 'lucide-react';

export default function InputBar({ input, onInputChange, onSubmit, isLoading }) {
  return (
    <footer className="p-6 bg-white dark:bg-zinc-900 border-t border-slate-100 dark:border-zinc-800">
      <form onSubmit={onSubmit} className="flex gap-3 mb-6 relative">
        <input
          type="text"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder="Bir mesaj yazın..."
          disabled={isLoading}
          aria-label="Mesaj giriş alanı"
          className="flex-1 p-4 rounded-xl border outline-none transition-all
            bg-white border-slate-300 text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500
            dark:bg-zinc-950 dark:border-zinc-700 dark:text-white dark:placeholder-zinc-600 dark:focus:border-zinc-500 dark:focus:ring-zinc-500"
        />
        <button
          type="submit"
          disabled={!input.trim() || isLoading}
          aria-label="Mesaj gönder"
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
  );
}
