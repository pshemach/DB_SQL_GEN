from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from ..config import settings
from ..graph.graph_state import AgentState
from ..utils.llm_factory import groq_llm


INTENT_SWITCH_PROMPT = """
You are a conversation controller.

Decide whether the user reply answers the previous question
or starts a new question.

Previous Original Question:
{previous_question}

System Asked:
{question_to_user}

User Reply:
{user_reply}

Return ONLY:
ANSWER
or
NEW_QUESTION

Rules:
- If user reply directly answers the system question, return ANSWER.
- If user changes topic, return NEW_QUESTION.
- If unclear, return NEW_QUESTION.
"""


class IntentSwitchAgent:
    def __init__(self):
        self.llm = groq_llm(temperature=0)


        self.prompt = ChatPromptTemplate.from_messages([
            ("system", INTENT_SWITCH_PROMPT),
            ("human", "{user_reply}")
        ])

        self.chain = self.prompt | self.llm

    def detect(self, previous_state: dict, user_reply: str) -> str:
        response = self.chain.invoke({
            "previous_question": previous_state.get("pending_original_question"),
            "question_to_user": previous_state.get("question_to_user"),
            "user_reply": user_reply
        })

        decision = response.content.strip()

        if decision not in {"ANSWER", "NEW_QUESTION"}:
            return "NEW_QUESTION"

        return decision


intent_switch_agent = IntentSwitchAgent()