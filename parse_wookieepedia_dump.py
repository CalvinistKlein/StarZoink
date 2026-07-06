import xml.etree.ElementTree as ET
import re
import os
import sys
import json
import requests
import chromadb
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load config dynamically from config.json
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

OLLAMA_URL = load_config_url()
EMBEDDING_MODEL = "nomic-embed-text"
MAX_THREADS = 24
BATCH_SIZE = 250

def clean_wikitext(text):
    """
    Strips raw MediaWiki markup into cleaner plain text for RAG chunking.
    """
    # Remove templates {{TemplateName | ...}}
    # (Using a loop to handle nested templates up to 3 levels deep)
    for _ in range(3):
        text = re.sub(r'\{\{[^{}]*\}\}', '', text)
        
    # Remove references/citations <ref>...</ref> and self-closing tags
    text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)
    text = re.sub(r'<ref[^>]*/>', '', text)
    
    # Convert links [[Target|Label]] -> Label
    text = re.sub(r'\[\[([^\]|]*)\|([^\]]*)\]\]', r'\2', text)
    # Convert links [[Target]] -> Target
    text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text)
    
    # Remove external links [http://example.com Label] -> Label
    text = re.sub(r'\[http[^\s]*\s+([^\]]*)\]', r'\1', text)
    
    # Remove bold/italic markup
    text = text.replace("'''", "").replace("''", "")
    
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    
    # Strip markdown headers, lists, table tags, etc.
    text = re.sub(r'^=+\s*(.*?)\s*=+$', r'\1', text, flags=re.MULTILINE)
    text = re.sub(r'^[*#]+', '', text, flags=re.MULTILINE)
    
    # Replace multiple spaces and newlines
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()

class WookieepediaDbParser:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, "StarWars_Wookepedia_2026_07_06")
        print(f"Initializing ChromaDB client at {db_path}...")
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        self.collection = self.chroma_client.get_or_create_collection(name="star_wars_lore")
        print(f"Connecting to embedding model server at {OLLAMA_URL}...")
        
    def get_embedding(self, text):
        url = f"{OLLAMA_URL}/api/embeddings"
        data = {
            "model": EMBEDDING_MODEL,
            "prompt": text
        }
        try:
            res = requests.post(url, json=data, timeout=30)
            if res.status_code == 200:
                return res.json().get("embedding", [])
        except Exception:
            pass
        return []

    def get_embeddings_parallel(self, paragraphs):
        embeddings = [None] * len(paragraphs)
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_idx = {executor.submit(self.get_embedding, para): i for i, para in enumerate(paragraphs)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    emb = future.result()
                    embeddings[idx] = emb
                except Exception:
                    embeddings[idx] = []
        return embeddings

    def write_batch(self, batch):
        if not batch:
            return 0
        
        ids = [item['doc_id'] for item in batch]
        
        # Query existing IDs to avoid duplicates/re-embedding
        try:
            existing = self.collection.get(ids=ids)
            existing_ids = set(existing.get('ids', []))
        except Exception:
            existing_ids = set()
            
        filtered_batch = [item for item in batch if item['doc_id'] not in existing_ids]
        if not filtered_batch:
            return 0
            
        paragraphs = [item['para'] for item in filtered_batch]
        filtered_ids = [item['doc_id'] for item in filtered_batch]
        metadatas = [{"source": "wookieepedia", "title": item['title']} for item in filtered_batch]
        
        # Get embeddings in parallel
        embeddings = self.get_embeddings_parallel(paragraphs)
        
        valid_ids = []
        valid_embeddings = []
        valid_documents = []
        valid_metadatas = []
        
        for i, emb in enumerate(embeddings):
            if emb:
                valid_ids.append(filtered_ids[i])
                valid_embeddings.append(emb)
                valid_documents.append(paragraphs[i])
                valid_metadatas.append(metadatas[i])
                
        if valid_ids:
            try:
                self.collection.add(
                    ids=valid_ids,
                    embeddings=valid_embeddings,
                    documents=valid_documents,
                    metadatas=valid_metadatas
                )
                return len(valid_ids)
            except Exception as e:
                print(f"\nError adding batch to ChromaDB: {e}")
        return 0

    def parse_dump(self, xml_file_path, limit=None):
        if not os.path.exists(xml_file_path):
            print(f"Error: XML dump file not found at {xml_file_path}")
            return
            
        print("Starting XML parsing. (Using streaming parser to save RAM...)")
        
        # Get root element to clear it periodically and prevent memory leaks
        context = ET.iterparse(xml_file_path, events=('start', 'end'))
        context = iter(context)
        
        # Get root
        try:
            event, root = next(context)
        except StopIteration:
            return
            
        # Extract namespace from root tag
        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}")[0] + "}"
            
        print(f"Detected XML namespace: {namespace}")
        
        page_count = 0
        chunk_count = 0
        batch = []
        
        for event, elem in context:
            if event == 'end':
                if elem.tag == f"{namespace}page":
                    title_elem = elem.find(f"{namespace}title")
                    ns_elem = elem.find(f"{namespace}ns")
                    revision_elem = elem.find(f"{namespace}revision")
                    
                    # We only want main namespace articles (ns = 0)
                    if ns_elem is not None and ns_elem.text == "0" and title_elem is not None:
                        title = title_elem.text
                        
                        # Ignore redirects and category/disambiguation pages
                        text_elem = revision_elem.find(f"{namespace}text") if revision_elem is not None else None
                        if text_elem is not None and text_elem.text:
                            body = text_elem.text
                            
                            if (not body.startswith("#REDIRECT") and 
                                not body.startswith("#redirect") and 
                                "disambig" not in title.lower() and 
                                "disambig" not in body.lower() and 
                                "may refer to:" not in body.lower()):
                                
                                page_count += 1
                                clean_body = clean_wikitext(body)
                                
                                # Chunk by paragraph (ignoring empty/tiny blocks)
                                paragraphs = [p.strip() for p in clean_body.split("\n\n") if len(p.strip()) > 100]
                                
                                for i, para in enumerate(paragraphs):
                                    doc_id = f"wook_{page_count}_{i}"
                                    batch.append({
                                        'doc_id': doc_id,
                                        'para': para,
                                        'title': title
                                    })
                                    
                                    if len(batch) >= BATCH_SIZE:
                                        inserted = self.write_batch(batch)
                                        chunk_count += inserted
                                        batch = []
                                        
                                if page_count % 100 == 0:
                                    print(f"Progress: Processed {page_count} articles, ingested {chunk_count} chunks so far...", flush=True)
                                    
                                if limit and page_count >= limit:
                                    print(f"Limit of {limit} articles reached. Stopping parser.")
                                    break
                                    
                    # Clear processed page element and references from root to save memory
                    elem.clear()
                    root.clear()
                
        # Write any remaining batch items
        if batch:
            inserted = self.write_batch(batch)
            chunk_count += inserted
            
        print(f"Finished! Successfully parsed {page_count} pages and generated embeddings.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_wookieepedia_dump.py <path_to_xml_file> [--limit <number>]")
        print("Example: python3 parse_wookieepedia_dump.py starwars_pages_current.xml --limit 500")
        sys.exit(1)
        
    xml_path = sys.argv[1]
    
    limit_val = None
    if "--limit" in sys.argv:
        try:
            limit_idx = sys.argv.index("--limit")
            limit_val = int(sys.argv[limit_idx + 1])
        except Exception:
            print("Invalid value for --limit option.")
            sys.exit(1)
            
    parser = WookieepediaDbParser()
    parser.parse_dump(xml_path, limit=limit_val)
