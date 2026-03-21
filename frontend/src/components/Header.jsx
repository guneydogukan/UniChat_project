/**
 * UniChat Frontend — Header Bileşeni
 * Logo, başlık, çevrimiçi durumu ve dark mode toggle.
 */

import { GraduationCap, Sun, Moon } from 'lucide-react';

export default function Header({ isDarkMode, onToggleDarkMode }) {
  return (
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
        onClick={onToggleDarkMode}
        className="p-3 rounded-full hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors text-slate-600 dark:text-zinc-400"
        aria-label={isDarkMode ? 'Açık temaya geç' : 'Koyu temaya geç'}
      >
        {isDarkMode ? <Sun className="w-6 h-6" /> : <Moon className="w-6 h-6" />}
      </button>
    </header>
  );
}
