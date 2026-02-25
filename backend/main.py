import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from haystack.components.generators import OpenAIGenerator
from haystack.utils import Secret

# .env dosyasını yükle
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

api_key = os.getenv("OPENROUTER_API_KEY")

# FastAPI uygulaması
app = FastAPI(title="UniChat API", version="1.0.0")

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemma 3 LLM — tek seferlik yapılandırma
llm = OpenAIGenerator(
    api_key=Secret.from_token(api_key),
    api_base_url="https://openrouter.ai/api/v1",
    model="google/gemma-3-27b-it:free",
)


# Request modeli
class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        result = llm.run(prompt=request.message)
        reply = result["replies"][0]
        return {"response": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)