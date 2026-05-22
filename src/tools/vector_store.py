"""
Vector store for dynamic few-shot example retrieval.
"""

from typing import List, Dict
from langchain_chroma import Chroma
from langchain_core.documents import Document
from .embeddings import get_embeddings
from loguru import logger
from ..config import settings
import os

class FewShotRetriever:
    """
    Manages a vector store of SQL examples for dynamic few-shot learning.
    """
    def __init__(self):
        self.enabled = settings.enable_dynamic_few_shot
        
        if not self.enabled:
            logger.info("Dynamic few-shot learning disabled")
            return
        
        self.embeddings = get_embeddings()
        
        # Initialize vector store
        persist_directory = settings.vector_store_path
        os.makedirs(persist_directory, exist_ok=True)
        
        self.vectorstore = Chroma(
            collection_name=settings.chroma_collection_name,
            embedding_function=self.embeddings,
            persist_directory=persist_directory
        )
        
        logger.info(f"Few-shot retriever initialized with ChromaDB")
        
    def add_example(self, question: str, sql: str, explanation: str = None, 
                    schema_context: str = None, complexity: str = "medium"):
        """
        Add a new SQL example to the vector store.
        
        Args:
            question: Natural language question
            sql: Corresponding SQL query
            explanation: Optional explanation
            schema_context: Optional schema info
            complexity: Difficulty level (simple, medium, complex)
        """
        if not self.enabled:
            return
        
        try:
            doc = Document(
                page_content=question,
                metadata={
                    "sql": sql,
                    "explanation": explanation,
                    "schema_context": schema_context,
                    "complexity": complexity
                }
            )
            self.vectorstore.add_documents([doc])
            logger.info(f"Added example: {question[:50]}...")
            
        except Exception as e:
            logger.error(f"Error adding example: {e}")
        
    def add_examples_batch(self, examples: List[Dict]):
        """
        Add multiple examples at once.
        
        Args:
            examples: List of example dicts with 'question', 'sql', etc.
        """
        if not self.enabled:
            return
        
        try:
            docs = []
            for ex in examples:
                doc = Document(
                    page_content=ex['question'],
                     metadata={
                        "sql": ex.get("sql", ""),
                        "explanation": ex.get("explanation", ""),
                        "schema_context": ex.get("schema_context", ""),
                        "complexity": ex.get("complexity", "medium")
                    }
                )
                docs.append(doc)
            
            self.vectorstore.add_documents(docs)
            logger.info(f"Added {len(docs)} examples to vector store")
            
        except Exception as e:
            logger.error(f"Error adding batch examples: {e}")
        
    def retrieve(self, question: str, k: int = None) -> List[Dict]:
        """
        Retrieve most relevant examples for a question.
        
        Args:
            question: User's question
            k: Number of examples to retrieve
            
        Returns:
            List of example dicts
        """
        if not self.enabled:
            return []
        
        k = k or settings.few_shot_examples_count
        
        try:
            # Similarity search
            results = self.vectorstore.similarity_search(question, k=k)
            
            examples = []
            for doc in results:
                examples.append({
                    "question": doc.page_content,
                    "sql": doc.metadata.get("sql", ""),
                    "explanation": doc.metadata.get("explanation", ""),
                    "schema_context": doc.metadata.get("schema_context", ""),
                    "complexity": doc.metadata.get("complexity", "medium")
                })
                
            logger.info(f"Retrieved {len(examples)} similar examples")
            return examples
            
        except Exception as e:
            logger.error(f"Error retrieving examples: {e}")
            return []
        
    def clear(self):
        """Clear all examples from vector store."""
        if self.enabled:
            # Delete and recreate collection
            self.vectorstore.delete_collection()
            logger.info("Vector store cleared")
            
# Global retriever instance
few_shot_retriever = FewShotRetriever()

def seed_examples():
    """
    Seed the vector store with common SQL patterns.
    This should be called during setup with your domain-specific examples.
    """
    if not settings.enable_dynamic_few_shot:
        return

    default_examples = [

    # ── Net Sales ──────────────────────────────────────────────────────────
    {
        "question": "What is my net sales this month?",
        "sql": """SELECT
    SUM(CASE WHEN sf.Type = 'sales' THEN sf.in_sales
             ELSE -sf.in_sales END) AS NetSales
FROM sales_flat AS sf
WHERE sf.RepCode = @RepCode
  AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
  AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)""",
        "explanation": "Net Sales = sales minus returns using CASE WHEN on Type column",
        "complexity": "simple"
    },

    # ── Productive Calls ───────────────────────────────────────────────────
    {
        "question": "What is my productive call count this month?",
        "sql": """WITH daily_pc AS (
    SELECT sf.RepId,
           CAST(sf.Date AS DATE)           AS visit_date,
           COUNT(DISTINCT sf.CustomerCode) AS daily_calls
    FROM sales_flat AS sf
    WHERE sf.Type = 'sales'
      AND sf.in_sales > 0
      AND sf.RepCode = @RepCode
      AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
      AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)
    GROUP BY sf.RepId, CAST(sf.Date AS DATE)
)
SELECT RepId, SUM(daily_calls) AS TotalProductiveCalls
FROM daily_pc
GROUP BY RepId""",
        "explanation": "Group by (RepId, Date) first in CTE, then sum to rep level",
        "complexity": "medium"
    },

    # ── Sales Target ───────────────────────────────────────────────────────
    {
        "question": "What is my sales target this month?",
        "sql": """SELECT shn.Code AS RepCode, SUM(st.Value) AS SalesTarget
FROM sales_targets AS st
JOIN sales_hierarchy_nodes AS shn ON shn.Id = st.RepId
WHERE shn.Code = @RepCode
  AND st.Type = 1
  AND st.StartDate <= LAST_DAY(CURRENT_DATE)
  AND st.EndDate   >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
GROUP BY shn.Code""",
        "explanation": "Type=1 is rep-level target. Join through sales_hierarchy_nodes",
        "complexity": "simple"
    },

    # ── Achievement vs Target (MUST use separate CTEs) ─────────────────────
    {
        "question": "What is my sales achievement vs target this month?",
        "sql": """WITH achievement AS (
    SELECT shn.Code AS RepCode,
           SUM(CASE WHEN sf.Type = 'sales' THEN sf.in_sales
                    ELSE -sf.in_sales END) AS NetSales
    FROM sales_flat AS sf
    JOIN sales_hierarchy_nodes AS shn ON shn.Id = sf.RepId
    WHERE shn.Code = @RepCode
      AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
      AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)
    GROUP BY shn.Code
),
target AS (
    SELECT shn.Code AS RepCode, SUM(st.Value) AS SalesTarget
    FROM sales_targets AS st
    JOIN sales_hierarchy_nodes AS shn ON shn.Id = st.RepId
    WHERE shn.Code = @RepCode
      AND st.Type = 1
      AND st.StartDate <= LAST_DAY(CURRENT_DATE)
      AND st.EndDate   >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
    GROUP BY shn.Code
)
SELECT a.RepCode,
       a.NetSales AS Achievement,
       t.SalesTarget,
       t.SalesTarget - a.NetSales AS Balance,
       ROUND(a.NetSales / NULLIF(t.SalesTarget, 0) * 100, 2) AS AchievementPct
FROM achievement AS a
JOIN target AS t ON t.RepCode = a.RepCode""",
        "explanation": "CRITICAL: aggregate sales and targets in SEPARATE CTEs to avoid row multiplication",
        "complexity": "complex"
    },

    # ── Bill Count ─────────────────────────────────────────────────────────
    {
        "question": "What is my total bill count this month?",
        "sql": """SELECT COUNT(DISTINCT sf.InvoiceNo)         AS BillCount,
       COUNT(DISTINCT sf.InvoiceNo) / 700.0 AS Productivity
FROM sales_flat AS sf
WHERE sf.Type = 'sales'
  AND sf.in_sales > 0
  AND sf.RepCode = @RepCode
  AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
  AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)""",
        "explanation": "COUNT(DISTINCT InvoiceNo) divided by monthly target (700)",
        "complexity": "simple"
    },

    # ── Zero Sales Outlets ─────────────────────────────────────────────────
    {
        "question": "What are my zero sales outlets this month?",
        "sql": """SELECT sf.CustomerName,
       MAX(sf.Date)                 AS LastBillingDate,
       COUNT(DISTINCT sf.InvoiceNo) AS VisitCount
FROM sales_flat AS sf
JOIN external_parties AS ep ON ep.Code = sf.CustomerCode
WHERE sf.in_sales = 0
  AND ep.Active = 1
  AND sf.RepCode = @RepCode
  AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
  AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)
  AND sf.CustomerName NOT IN (
      'Head Office','OPENING STOCK','INTERNAL SUPPLIER',
      'INTERNAL CUSTOMER','CASH','D_ON','D_OFF',
      'TOUR_START','TOUR_END','C Basnayaka-Matara 01'
  )
GROUP BY sf.CustomerName
LIMIT 100""",
        "explanation": "Zero sales = in_sales=0. Always include LastBillingDate and VisitCount. Always exclude internal names.",
        "complexity": "medium"
    },

    # ── Best Performing Outlets ────────────────────────────────────────────
    {
        "question": "Who are my best performing outlets / top customers?",
        "sql": """SELECT sf.CustomerName,
       SUM(CASE WHEN sf.Type = 'sales' THEN sf.in_sales
                ELSE -sf.in_sales END) AS NetSales
FROM sales_flat AS sf
WHERE sf.RepCode = @RepCode
  AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
  AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)
GROUP BY sf.CustomerName
ORDER BY NetSales DESC
LIMIT 10""",
        "explanation": "Best outlets = highest Net Sales (sales minus returns)",
        "complexity": "simple"
    },

    # ── Total Returns ──────────────────────────────────────────────────────
    {
        "question": "What is the total return amount this month?",
        "sql": """SELECT SUM(sf.in_sales) AS TotalReturnAmount
FROM sales_flat AS sf
WHERE sf.Type = 'return'
  AND sf.RepCode = @RepCode
  AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
  AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)""",
        "explanation": "Returns = SUM(in_sales) where Type='return'. Financial loss, not quantity.",
        "complexity": "simple"
    },

    # ── Average SKU per Bill ───────────────────────────────────────────────
    {
        "question": "What is the average SKU per bill this month?",
        "sql": """SELECT ROUND(AVG(sku_per_bill), 2) AS AvgSKUPerBill
FROM (
    SELECT sf.InvoiceNo,
           COUNT(DISTINCT sf.ProductCode) AS sku_per_bill
    FROM sales_flat AS sf
    WHERE sf.Type = 'sales'
      AND sf.in_sales > 0
      AND sf.RepCode = @RepCode
      AND sf.Date >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
      AND sf.Date <  DATE_ADD(DATE_FORMAT(CURRENT_DATE, '%Y-%m-01'), INTERVAL 1 MONTH)
    GROUP BY sf.InvoiceNo
) AS invoice_sku""",
        "explanation": "SKU = unique products per invoice. Return overall average, not total.",
        "complexity": "medium"
    },

]
    
    few_shot_retriever.add_examples_batch(default_examples)
    logger.info(f"Seeded {len(default_examples)} default examples")
