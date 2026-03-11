/**
 * UniChat Frontend — WelcomeScreen Bileşeni
 * Karşılama ekranı ve hızlı soru kartları.
 */

const QUICK_QUESTIONS = [
  'Yemekhane kuralları nelerdir?',
  'Bitirme projesi teslim tarihi ne zaman?',
  'Bir dönemde kaç kredi alabilirim?',
  'Yaz okulu başvuruları ne zaman?',
];

export default function WelcomeScreen({ onQuestionClick }) {
  return (
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
        {QUICK_QUESTIONS.map((q, idx) => (
          <button
            key={idx}
            onClick={() => onQuestionClick(q)}
            className="p-4 text-left rounded-xl transition-all border shadow-sm
              bg-white border-slate-200 hover:bg-slate-50 text-slate-700
              dark:bg-zinc-900 dark:border-zinc-700 dark:hover:bg-zinc-800 dark:text-zinc-300"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
