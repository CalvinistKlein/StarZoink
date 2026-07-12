import os
import json
import requests

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = False


def load_config_url():
    url = "http://localhost:11434"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
                url = cfg.get("OLLAMA_URL", url)
        except Exception:
            pass
    if url and not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    return url


EMBEDDING_MODEL = "nomic-embed-text"


class RagEngine:
    def __init__(self, db_path=None, ollama_url=None):
        self.ollama_url = ollama_url or load_config_url()
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, "StarWars_Wookepedia_2026_07_06")
        self.collection = None
        if not CHROMADB_AVAILABLE:
            print("Warning: chromadb not installed. RAG lore lookup disabled (narrator still works).")
            return
        try:
            print("Initializing ChromaDB...")
            self.chroma_client = chromadb.PersistentClient(path=db_path)
            self.collection = self.chroma_client.get_or_create_collection(name="star_wars_lore")
        except Exception as e:
            print(f"Warning: ChromaDB init failed: {e}. RAG disabled.")
            self.collection = None

    def get_embedding(self, text):
        url = f"{self.ollama_url}/api/embeddings"
        data = {
            "model": EMBEDDING_MODEL,
            "prompt": text
        }
        try:
            res = requests.post(url, json=data, timeout=30)
            if res.status_code == 200:
                return res.json().get("embedding", [])
        except Exception as e:
            print(f"Failed to get embedding from {self.ollama_url}: {e}")
        return []

    def ingest_knowledge_base(self, kb_path="KnowledgeBase"):
        if self.collection is None:
            print("RAG disabled; skipping ingestion.")
            return

        if not os.path.exists(kb_path):
            print(f"Directory {kb_path} does not exist.")
            return

        print("Scanning KnowledgeBase directory...")
        files_processed = 0

        for filename in os.listdir(kb_path):
            if filename.endswith(".txt"):
                file_path = os.path.join(kb_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Simple chunking by paragraph (discarding very short lines)
                paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 50]

                print(f"Processing '{filename}' ({len(paragraphs)} paragraphs)...")

                for i, para in enumerate(paragraphs):
                    doc_id = f"{filename}_chunk_{i}"

                    # Check if already embedded
                    existing = self.collection.get(ids=[doc_id])
                    if not existing['ids']:
                        emb = self.get_embedding(para)
                        if emb:
                            self.collection.add(
                                ids=[doc_id],
                                embeddings=[emb],
                                documents=[para],
                                metadatas=[{"source": filename}]
                            )
                files_processed += 1
                print(f"Finished ingesting {filename}")

        print(f"RAG Ingestion complete. {files_processed} files processed.")

    def query_lore(self, query_text, n_results=2):
        """
        Retrieves the most relevant paragraphs of lore from the local database.
        Returns "" if RAG is disabled or nothing matches.
        """
        if self.collection is None:
            return ""

        query_emb = self.get_embedding(query_text)
        if not query_emb:
            return ""

        try:
            results = self.collection.query(
                query_embeddings=[query_emb],
                n_results=n_results
            )

            if results and results['documents'] and results['documents'][0]:
                return "\n\n".join(results['documents'][0])
        except Exception as e:
            print(f"ChromaDB Query Error: {e}")

        return ""


if __name__ == "__main__":
    # Test execution
    rag = RagEngine()
    rag.ingest_knowledge_base()

    test_query = "TIE Interceptor weapons"
    print(f"\nTesting Query for: '{test_query}'")
    result = rag.query_lore(test_query)

    if result:
        print("\n--- RESULTS FOUND ---")
        print(result)
    else:
        print("\nNo results found. (Did you scrape any articles yet?)")
