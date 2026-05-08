from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from ..config import settings
from ..prompt import KNOWLEDGE_GAP_DETECTOR_PROMPT
from ..utils.json_utils import extract_json
from ..tools import business_knowledge_store, business_knowledge_retriever
from ..core import AgentState


class KnowledgeGapDetectorAgent:
    def __init__(self):
        self.llm = ChatAnthropic(
            model_name=settings.anthropic_model_fast,
            api_key=settings.anthropic_api_key
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", KNOWLEDGE_GAP_DETECTOR_PROMPT),
            ("human", "{question}")
        ])
        
        self.chain = self.prompt | self.llm
        
    def detect(self, state: AgentState) -> dict: 
        print(state)
        question = state['question']
        session_id = state['session_id']
        
        memory_context = state['memory_context'] or ""
        
        keyword_matches = business_knowledge_store.keyword_search(question)
        
        keyword_knowledge = "\n".join(
            f"KPI: {m['name']}\n{m['definition']}"
            for m in keyword_matches
        )
        
        vector_knowledge = ""
        if business_knowledge_retriever:
            try:
                vector_knowledge = business_knowledge_retriever.retrieve(question)
            except Exception as e:
                logger.warning(f"Vector knowledge retrieval failed: {e}")

        retrieved_knowledge = "\n\n".join(
            x for x in [keyword_knowledge, vector_knowledge] if x
        )

        try:
            response = self.chain.invoke({
                "question": question,
                "memory_context": memory_context,
                # "business_definitions": business_knowledge_store.get_all_definitions_text(),
                "retrieved_knowledge": retrieved_knowledge
            })

            result = extract_json(response.content)

            needs = bool(result.get("needs_clarification", False))
            gap_type = result.get("gap_type", "none")

            if gap_type == "none":
                needs = False

            return {
                "needs_clarification": needs,
                "gap_type": gap_type,
                "confidence": float(result.get("confidence", 0.0)),
                "gap_reason": result.get("gap_reason"),
                "missing_pieces": result.get("missing_pieces", []),
                "business_definitions": result.get("business_definitions") or retrieved_knowledge,
                "matched_knowledge": keyword_matches
            }

        except Exception as e:
            logger.error(f"Knowledge gap detection failed: {e}")

            return {
                "needs_clarification": True,
                "gap_type": "knowledge_gap",
                "confidence": 0.0,
                "gap_reason": "Unable to verify business knowledge coverage.",
                "missing_pieces": ["business definition"],
                "business_definitions": retrieved_knowledge,
                "matched_knowledge": keyword_matches
            }
            
def knowledge_gap_detector_node(state: dict) -> dict:
    return KnowledgeGapDetectorAgent().detect(state)