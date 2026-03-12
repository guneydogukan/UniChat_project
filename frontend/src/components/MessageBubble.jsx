/**
 * UniChat Frontend — MessageBubble Bileşeni
 * Kullanıcı ve bot mesaj baloncukları + kaynak kartları + markdown rendering.
 */

import { Bot, ExternalLink, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  const isError = message.isError || false;
  const sources = message.sources || [];

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

      <div className="max-w-[85%] md:max-w-[75%] space-y-2">
        {/* Mesaj Baloncuğu */}
        <div
          className={`p-4 rounded-2xl text-sm md:text-base leading-relaxed shadow-sm
            ${isUser
              ? 'bg-blue-600 text-white rounded-br-none'
              : isError
                ? 'bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300 rounded-bl-none border border-red-200 dark:border-red-800/50'
                : 'bg-slate-100 text-slate-800 dark:bg-zinc-800 dark:text-zinc-200 rounded-bl-none border border-slate-200 dark:border-zinc-700'
            }`}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-a:text-blue-600 dark:prose-a:text-blue-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Kaynak Kartları */}
        {!isUser && sources.length > 0 && (
          <div className="space-y-1.5 pl-1">
            <p className="text-xs font-medium text-slate-400 dark:text-zinc-500 flex items-center gap-1">
              <FileText className="w-3 h-3" />
              Kaynaklar
            </p>
            <div className="flex flex-wrap gap-2">
              {sources.map((src, idx) => (
                <SourceCard key={idx} source={src} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SourceCard({ source }) {
  const label = source.category || 'Belge';

  return (
    <div className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border transition-colors
      bg-white border-slate-200 text-slate-600 hover:bg-slate-50
      dark:bg-zinc-900 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
    >
      <FileText className="w-3 h-3 flex-shrink-0" />
      <span className="truncate max-w-[200px]">{label}</span>
      {source.source_url && (
        <a
          href={source.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-500 dark:text-blue-400 hover:text-blue-600 dark:hover:text-blue-300"
          title={source.source_url}
        >
          <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}
