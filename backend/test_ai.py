import os
import sys
from dotenv import load_dotenv
from haystack.components.generators import OpenAIGenerator
from haystack.utils import Secret

# .env dosyasını yükle (proje kök dizininden)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

api_key = os.getenv("OPENROUTER_API_KEY")


def test_gemma():
    """OpenRouter üzerinden Gemma 3 modeline test mesajı gönderir."""
    try:
        generator = OpenAIGenerator(
            api_key=Secret.from_token(api_key),
            api_base_url="https://openrouter.ai/api/v1",
            model="google/gemma-3-27b-it:free",
        )

        prompt = "Merhaba, sen kimsin ve bana nasıl yardımcı olabilirsin? Lütfen Türkçe ve çok kısa cevap ver."

        print("📡 Gemma 3 modeline bağlanılıyor...\n")
        result = generator.run(prompt=prompt)

        reply = result["replies"][0]
        print(f"🤖 Gemma 3 Diyor ki:\n{reply}")
        print("\n✅ AI bağlantı testi başarılı!")

    except Exception as e:
        print(f"\033[91m❌ Bağlantı hatası: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    test_gemma()
