"""
Vector store for dynamic database schema and table retrieval.
Indexes database tables, columns, and descriptions for first-stage pruning.
"""

from typing import List, Dict, Any, Optional
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from loguru import logger
from ..config import settings
from ..core.database import db_manager
import os

class SchemaVectorStore:
    """
    Manages a vector store of database table structures and descriptions.
    Enables rapid first-stage schema pruning by searching for relevant tables.
    """
    def __init__(self):
        # Initialize embeddings with the configured model
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedding_model
        )
        
        # Initialize vector store directory
        persist_directory = settings.vector_store_path
        os.makedirs(persist_directory, exist_ok=True)
        
        self.vectorstore = Chroma(
            collection_name="schema_vectors",
            embedding_function=self.embeddings,
            persist_directory=persist_directory
        )
        
        logger.info("SchemaVectorStore: Initialized ChromaDB for schema retrieval.")
        
    def index_all_tables(self):
        """
        Dynamically extracts all tables from the database, builds their documents,
        and indexes them in the Chroma vector store.
        """
        logger.info("SchemaVectorStore: Beginning dynamic database schema indexing...")
        
        try:
            # 1. Clear existing collection to avoid duplicates
            try:
                self.vectorstore.delete_collection()
                # Re-initialize collection after deletion
                self.vectorstore = Chroma(
                    collection_name="schema_vectors",
                    embedding_function=self.embeddings,
                    persist_directory=settings.vector_store_path
                )
            except Exception as e:
                logger.warning(f"SchemaVectorStore: Collection clear warning: {e}")
            
            # 2. Get all tables in the database
            all_tables = db_manager.get_all_table_names()
            logger.info(f"SchemaVectorStore: Found {len(all_tables)} tables to index.")
            
            # Rich descriptions for key tables to ensure precise semantic matching
            core_table_descriptions = {
                "sales_flat": (
                    "Main flat table that stores product-wise sales and return data for each sales representative (rep). "
                    "Contains transaction details, invoices, invoice line rows, quantities (Qty), return values, sales values, "
                    "net sales, customer information (CustomerCode, CustomerName), rep details (RepCode, RepName, RepId), "
                    "date (Date), invoice number (InvoiceNo), product details (ProductCode, ProductName), "
                    "product category, brand, route, ASM, RSM, distributor, and type (sales vs return)."
                ),
                "sales_targets": (
                    "Contains target values and quotas assigned to sales representatives (reps) or distributors. "
                    "Includes target value, rep ID (RepId), start date (StartDate), end date (EndDate), target type (Type: 1 for rep level, 0 for distributor level), "
                    "and targeted products or customers."
                ),
                "sales_hierarchy_nodes": (
                    "Hierarchical structure mapping table for sales hierarchy nodes, reps, ASMs, and RSMs. "
                    "Acts as the mandatory bridge to join sales_flat (sf.RepId) and sales_targets (st.RepId) by matching RepCode/Code. "
                    "Contains Id and Code columns."
                ),
                "external_parties": (
                    "Customer and supplier master details. Contains information on all retail outlets, customers, distributor names, "
                    "active status (Active=1 for active outlets), credit approvals, and party categories."
                ),
                "products": (
                    "Product master catalog. Stores product codes, product names, categories, brands, sub-categories, "
                    "and unit volumes in litres or kilograms (Litre, Kg, Volume). Crucial for calculating volume-based metrics."
                ),
                "planned_routes": (
                    "Planned route schedules for sales representatives. Maps RepId, RouteId, and PlannedDate to determine scheduled visits."
                ),
                "route_customer_assignments": (
                    "Assignments of customers/outlets to specific sales routes. Connects RouteId and CustomerId."
                )
            }
            
            docs = []
            for table in all_tables:
                metadata = db_manager.get_table_metadata(table)
                columns = [c.get("name") for c in metadata.get("columns", [])]
                
                # Fetch customized description or fallback to generic schema text
                description = core_table_descriptions.get(
                    table, 
                    f"Database table '{table}' containing columns: {', '.join(columns)}."
                )
                
                # Build page content with table name, description, and column signatures
                page_content = f"Table: {table}\nDescription: {description}\nColumns: {', '.join(columns)}"
                
                doc = Document(
                    page_content=page_content,
                    metadata={
                        "table_name": table,
                        "column_count": len(columns)
                    }
                )
                docs.append(doc)
                
            if docs:
                self.vectorstore.add_documents(docs)
                logger.info(f"SchemaVectorStore: Successfully indexed {len(docs)} tables.")
                
        except Exception as e:
            logger.error(f"SchemaVectorStore: Failed to index database schema: {e}")
            
    def retrieve_candidate_tables(self, question: str, k: int = 12) -> List[str]:
        """
        Retrieves the top k candidate tables matching a user question.
        
        Args:
            question: Natural language query or plan
            k: Maximum number of tables to return
            
        Returns:
            List of unique table names
        """
        try:
            results = self.vectorstore.similarity_search(question, k=k)
            candidates = []
            for doc in results:
                table_name = doc.metadata.get("table_name")
                if table_name and table_name not in candidates:
                    candidates.append(table_name)
            
            # Always ensure the 7 core tables are present in the list if the search missed them
            # to preserve backward compatibility for standard operations
            core_tables = [
                "sales_flat", "sales_targets", "sales_hierarchy_nodes",
                "external_parties", "products", "planned_routes", "route_customer_assignments"
            ]
            
            # Ensure core tables are added at the beginning or prioritised
            for t in core_tables:
                if t in db_manager.get_all_table_names() and t not in candidates:
                    candidates.append(t)
                    
            logger.info(f"SchemaVectorStore: Retrieved candidate tables: {candidates}")
            return candidates
            
        except Exception as e:
            logger.error(f"SchemaVectorStore: Table similarity search failure: {e}")
            # Fallback to absolute core tables
            return [
                "sales_flat", "sales_targets", "sales_hierarchy_nodes",
                "external_parties", "products", "planned_routes", "route_customer_assignments"
            ]

# Global schema vector store instance
schema_vector_store = SchemaVectorStore()
