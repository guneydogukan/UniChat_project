"""Debug: Pipeline output inspection with explicit logging"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services.rag_service import RagService

service = RagService()
service.build_pipeline()

question = "Bilgisayar muhendisligi hakkinda bilgi"

result = service._pipeline.run({
    "text_embedder": {"text": question},
    "keyword_retriever": {"query": question},
    "prompt_builder": {"question": question},
})

# Write full pipeline output analysis to file
with open("debug_output.txt", "w", encoding="utf-8") as f:
    f.write(f"Pipeline result keys: {list(result.keys())}\n\n")
    
    for key in result:
        f.write(f"\n=== {key} ===\n")
        sub = result[key]
        if isinstance(sub, dict):
            for k2, v2 in sub.items():
                if k2 == "documents":
                    f.write(f"  {k2}: {len(v2)} documents\n")
                    for i, doc in enumerate(v2[:5]):
                        title = doc.meta.get("title", "?") if doc.meta else "?"
                        source = doc.meta.get("source_url", "?") if doc.meta else "?"
                        cat = doc.meta.get("category", "?") if doc.meta else "?"
                        score = doc.score if hasattr(doc, 'score') else "N/A"
                        content_preview = doc.content[:100].replace("\n"," ") if doc.content else "EMPTY"
                        f.write(f"    [{i}] score={score}\n")
                        f.write(f"         title={title[:80]}\n")
                        f.write(f"         cat={cat} url={source[:100]}\n")
                        f.write(f"         content={content_preview}...\n")
                elif k2 == "replies":
                    f.write(f"  {k2}: {len(v2)} replies\n")
                    if v2:
                        f.write(f"  first reply length: {len(v2[0])} chars\n")
                elif k2 == "meta":
                    f.write(f"  {k2}: {v2}\n")
                else:
                    f.write(f"  {k2}: {type(v2).__name__} = {str(v2)[:200]}\n")
        else:
            f.write(f"  type: {type(sub).__name__}\n")

    # Now test query() method
    f.write(f"\n\n=== RagService.query() ===\n")
    result2 = service.query(question)
    f.write(f"Response length: {len(result2['response']) if result2['response'] else 0}\n")
    f.write(f"Sources count: {len(result2['sources'])}\n")
    for i, src in enumerate(result2['sources'][:5]):
        f.write(f"  [{i}] {json.dumps(src, ensure_ascii=False)}\n")

print("Debug output written to debug_output.txt")
