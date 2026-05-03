# from src.agents import planner_node, schema_linker_node, generator_node
# from src.core import AgentState

# state = AgentState(question="I am rep RepCode MATREP001, What is my productive call?")


# planner_node_output = planner_node(state)

# print(planner_node_output['plan'])
# print( planner_node_output['plan_steps'])

# state['plan'] = planner_node_output['plan']
# state['plan_steps'] = planner_node_output['plan_steps']

# schema_linker_node_output = schema_linker_node(state)

# print(schema_linker_node_output['relevant_tables'])

# state['relevant_tables'] = schema_linker_node_output['relevant_tables']
# state['schema_context'] = schema_linker_node_output['schema_context']
# state['schema_metadata'] = schema_linker_node_output['schema_metadata']


# generator_node_output = generator_node(state)

# print(generator_node_output['sql_query'])


from src.graph import run_agent

question = "I am rep RepCode MATREP001, What is my sales target?"

final_state = run_agent(question)

print(final_state['sql_query'])