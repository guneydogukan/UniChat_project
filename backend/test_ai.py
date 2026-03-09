from haystack_integrations.components.generators.ollama import OllamaGenerator
import traceback

print("🤖 Ollama motoru başlatılıyor...")
try:
    # Sadece jeneratörü kuruyoruz
    generator = OllamaGenerator(model="gemma3:4b-it-qat", url="http://localhost:11434")

    print("⏳ Modele soru gönderiliyor (Lütfen bekleyin)...")
    # Doğrudan jeneratöre soruyu veriyoruz
    result = generator.run(prompt="Türkiye'nin başkenti neresidir? Sadece şehir adını söyle.")
    print("✅ BAŞARILI! Modelden gelen cevap:")
    print("--------------------------------------------------")
    print(result["replies"][0])
    print("--------------------------------------------------")

except Exception as e:
    print("❌ BİR HATA OLUŞTU:")
    traceback.print_exc()
