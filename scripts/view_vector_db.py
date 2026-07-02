import sys 
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from src.agents.tools.business_knowledge_retriever import business_knowledge_retriever

def main():
    vectorstore = business_knowledge_retriever.vectorstore
    all_docs = vectorstore.get()
    
    data = []
    if all_docs and all_docs.get('documents'):
        for i, doc in enumerate(all_docs['documents']):
            metadata = all_docs['metadatas'][i] if all_docs.get('metadatas') else {}
            data.append({
                'Name': metadata.get('name', ''),
                'Keywords': ', '.join(metadata.get('keywords', [])),
                'Definition': doc,
                'ID': all_docs['ids'][i] if all_docs.get('ids') else ''
            })
    
    df = pd.DataFrame(data)
    
    # Display options
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    
    print("\n📊 Business Vector Store Contents")
    print("=" * 100)
    print(df.to_string(index=False))
    print(f"\n✅ Total KPIs in Vector Store: {len(df)}")
    
    return df

if __name__ == "__main__":
    df = main()