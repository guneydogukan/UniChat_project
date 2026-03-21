/**
 * UniChat Frontend — ChatArea Bileşeni
 * Mesaj listesi container.
 */

import MessageBubble from './MessageBubble';
import LoadingIndicator from './LoadingIndicator';
import WelcomeScreen from './WelcomeScreen';

export default function ChatArea({ messages, isLoading, messagesEndRef, onQuestionClick }) {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar bg-white dark:bg-zinc-900">
      {messages.length === 0 ? (
        <WelcomeScreen onQuestionClick={onQuestionClick} />
      ) : (
        <>
          {messages.map((msg, idx) => (
            <MessageBubble key={idx} message={msg} />
          ))}
          {isLoading && <LoadingIndicator />}
          <div ref={messagesEndRef} />
        </>
      )}
    </div>
  );
}
