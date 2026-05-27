from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from ..config import settings
from ..graph.graph_state import AgentState
from ..utils.llm_factory import groq_llm

CONVERSATION_ROUTER_PROMPT = """
You are a conversation router.

Decide whether the latest user message is:
1. clarification_answer
2. new_question

Previous Original Question:
{previous_question}

System Asked:
{question_to_user}

Latest User Message:
{question}

Rules:
- If latest message directly answers the system question, return clarification_answer.
- If latest message changes topic or asks a new report/query, return new_question.
- If there is no previous waiting question, return normal_question.
- If unsure, return new_question.

Return ONLY one:
normal_question
clarification_answer
new_question
"""


class ConversationRouterAgent:
    def __init__(self):
        # self.llm = ChatOpenAI(
        #     model=settings.openai_model_fast,
        #     api_key=settings.openai_api_key,
        #     temperature=0
        # )
        
        # self.llm = ChatAnthropic(
        #     model=settings.anthropic_model_fast,
        #     api_key=settings.anthropic_api_key
        # )
        
        self.llm = groq_llm()


        self.prompt = ChatPromptTemplate.from_messages([
            ("system", CONVERSATION_ROUTER_PROMPT),
            ("human", "{question}")
        ])

        self.chain = self.prompt | self.llm

    def route(self, state: dict) -> dict:
        previous_state = state.get("previous_state")

        if not previous_state or not previous_state.get("waiting_for_user"):
            return {"conversation_route": "normal_question"}

        response = self.chain.invoke({
            "previous_question": previous_state.get("pending_original_question"),
            "question_to_user": previous_state.get("question_to_user"),
            "question": state["question"]
        })

        route = response.content.strip()

        if route not in {"normal_question", "clarification_answer", "new_question"}:
            route = "new_question"

        return {"conversation_route": route}


def conversation_router_node(state: dict) -> dict:
    return ConversationRouterAgent().route(state)