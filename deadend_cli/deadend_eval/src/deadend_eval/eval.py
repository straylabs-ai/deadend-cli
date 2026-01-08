# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Evaluation framework for AI agent performance and security research.

This module provides evaluation functionality for testing AI agent performance,
security research capabilities, and workflow effectiveness using various
evaluation metrics and testing scenarios.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
import docker
from pydantic import BaseModel, Field
from deadend_agent import (
    AIModel,
    RetrievalDatabaseConnector,
    Sandbox,
    DeadEndAgent
)
from deadend_agent.models.registry import EmbedderClient
from deadend_eval.metrics import (
    instrument_agent_runner,
    global_metrics,
    metrics_to_markdown,
    metrics_to_json
)

class Subtask(BaseModel):
    """Represents a single subtask in a guided evaluation workflow.
    
    Contains all information needed to execute and validate a specific
    component of a security challenge evaluation.
    
    Attributes:
        subtask: High-level description of the subtask objective
        question: Specific question to be answered for this subtask
        hints: List of helpful hints for approaching the question
        solution: Expected answer or solution for validation
    """
    subtask: str = Field(..., description="subtask step generalized")
    question: str = Field(..., description="Question specified to achieve to subtask")
    hints: list[str] = Field(..., description="Hints on how to answer the question")
    solution: str = Field(..., description="Answer to the subtask")

class EvalMetadata(BaseModel):
    """Metadata containing all information about a security challenge evaluation.
    
    Defines the complete context, parameters, and validation criteria for
    evaluating AI agent performance on security challenges.
    
    Attributes:
        name: Human-readable name of the challenge
        categories: List of challenge categories (e.g., ['web', 'crypto'])
        difficulty: Challenge difficulty level (e.g., 'Easy', 'Medium', 'Hard')
        assets_path: File system path to challenge assets and files
        target_host: Host address or URL for the target system
        soft_prompt: Prompt with minimal guidance information
        hard_prompt: Prompt with detailed guidance and hints
        subtasks: List of subtasks for guided evaluation mode
        validation_type: Type of validation ('flag' or 'canary')
        validation_format: Description of expected solution format
        solution: Expected challenge solution for validation
    """
    name: str = Field(..., description="Name of the challenge")
    categories: list[str] = Field(..., description="Challenge categories")
    difficulty: str = Field(..., description="Challenge difficulty")
    assets_path: str = Field(..., description="Path to the different challenge assets.")
    target_host: str = Field(..., description="Target host, could be a hostname, IP adress...")
    soft_prompt: str = Field(..., description="Corresponds to a prompt with minimal information")
    hard_prompt: str = Field(..., description="prompt that adds more information to the target")
    subtasks: list[Subtask] = Field(..., description="Subtasks if guided mode is on")
    validation_type: Literal['flag', 'canary'] = Field(..., description="Defines the type of validation to know if the solution is of the type of what the agent found.")
    validation_format: str = Field(..., description="Format of the validation type. It gives hints and information of what the solution could be.")
    solution: str = Field(..., description="Solution of the challenge that could be used with LLM-as-Judge if not simple flag.")

async def eval_deadend_agent(
        model: AIModel,
        embedder_client: EmbedderClient,
        # evaluators: list[Evaluator],
        code_indexer_db: RetrievalDatabaseConnector,
        sandbox: Sandbox,
        eval_metadata: EvalMetadata,
        hard_prompt: bool,
        # choosing between hard and soft prompt
        guided: bool,
        # If guided enabled, the evaluation runs also on the subtasks
        human_intervention: bool,
        # whether or not ask user to specify information.
        with_context_engine: bool,
        # With context engineering enabled
        with_code_indexing: bool,
        # With code indexing enabled, code RAG specific to the application
        with_knowledge_base: bool,
        # Knowledge base represents the database RAG added for notes or technical documents.
        output_report: str
    ):
    """Evaluate an AI agent's performance on a security challenge.
    
    Executes a comprehensive evaluation of an AI agent against a specific security
    challenge, including target indexing, agent workflow execution, and result validation.
    
    Args:
        model: AI model instance to evaluate
        config: Configuration object containing API keys and settings
        code_indexer_db: Database connector for code indexing and retrieval
        sandbox: Sandbox environment for secure command execution
        eval_metadata: Complete metadata defining the challenge and evaluation parameters
        hard_prompt: Whether to use detailed (hard) or minimal (soft) prompting
        guided: Whether to use guided subtask-based evaluation
        human_intervention: Whether to pause for human input during evaluation
        with_context_engine: Whether to use advanced context engineering
        with_code_indexing: Whether to perform code indexing of the target
        with_knowledge_base: Whether to use knowledge base RAG capabilities
        output_report: Path where evaluation results should be saved
        
    Returns:
        Async evaluation results including agent performance metrics
        
    Raises:
        Various exceptions depending on evaluation step failures
        
    Note:
        This function orchestrates the complete evaluation pipeline including
        target preparation, agent execution, validation, and reporting.
    """

    # Ensure AgentRunner.run is instrumented for metrics collection.
    global_metrics.reset()
    instrument_agent_runner(global_metrics)

    generic_agents = {
        'requester': "Agent specialized in fine-grained testing and sending raw request data. Capable of handling authentication (session and token). Uses pupeteer in the background. Capable of exploring APIs and websites. Best for gathering auth tokens, testing individual endpoints, and precise request manipulation. Should NOT be used for automation tasks such as fuzzing or repetitive tasks that need iteration - use python_interpreter for those tasks instead.",
        'python_interpreter': "Agent specialized in generating code and running it. Each code generated is ran safely in a sandboxed webassembly. Best for fuzzing, parameter testing, generating testing exploits, and repetitive security testing operations that require iteration. Use this agent for tasks that need automation, loops, or multiple iterations.",
        'shell': "Agent that gives access to a terminal bash shell. Run linux commands here. DO NOT have access to target source code.",
        'router_agent': 'Router agent, expert that routes to the specific agent needed to achieve the next step of the plan.'
    }


    # workflow_agent.register_sandbox_runner(network_name="shared_net")
    # Setting up the prompt used
    if hard_prompt:
        prompt = eval_metadata.hard_prompt
    else:
        prompt = eval_metadata.soft_prompt

    # Resolve the target host. Metadata may provide a docker container name,
    # or a raw IP/host. When we detect the "container:port" form, we look up
    # the container's IP; otherwise we pass the value through unchanged.
    container_parts = eval_metadata.target_host.split(":")
    if len(container_parts) == 2:
        container_name, port = container_parts
        ip_addr_target = container_name
        try:
            docker_client = docker.from_env()
            target_container = docker_client.containers.get(container_name)
            ip_addr_target = target_container.attrs["NetworkSettings"]["Networks"]["shared_net"]["IPAddress"]
            print(f"the target ip : {ip_addr_target}")
        except docker.errors.NotFound:
            print(f"No container named {container_name}, using provided target host directly.")
        target_host = f"{ip_addr_target}:{port}"
    else:
        target_host = eval_metadata.target_host

    session_id = uuid4()
    deadend_agent = DeadEndAgent(
        session_id=session_id,
        model=model,
        available_agents=generic_agents,
        max_depth=2
    )
    # Set challenge name for trace file naming
    deadend_agent.challenge_name = eval_metadata.name

    if with_code_indexing:
        deadend_agent.init_webtarget_indexer(target_host)
        web_resources_crawler = await deadend_agent.crawl_target()
        code_chunks = await deadend_agent.embed_target(
            embedder_client=embedder_client
        )

        insert = await code_indexer_db.batch_insert_code_chunks(code_chunks_data=code_chunks)
        # console_printer.print("Sync completed.", end="\r")

    deadend_agent.prepare_dependencies(
        embedder_client=embedder_client,
        rag_connector=code_indexer_db,
        sandbox=sandbox,
        target=target_host
    )
    solved = False
    plan, threat_model_data, validation_token = await deadend_agent.threat_model(task=prompt)
    if validation_token and len(validation_token) > 1 and eval_metadata.solution:
        solved = (validation_token == eval_metadata.solution)
        print(f"Validation check: expected={eval_metadata.solution}, got={validation_token}, solved={solved}")
    else:
        print("Validation check: Continuing to the exploitation phase.")

    print(f"Plan produced is : {plan}")
    print(f"threat model is : {threat_model_data}")
    # if threat_model_data.output:
    #     print(f"Threat model is :\n{threat_model_data.output}")
    #     threat_model_computed = threat_model_data.output.summarized_context
    # else:
    #     print(f"Threat model is :\n{threat_model_data[0].parts[0].content}")
    #     threat_model_computed = threat_model_data[0].parts[0].content
    threat_model_computed = threat_model_data
    if not solved:
        if len(validation_token) > 1:
            threat_model_computed += f"## Important NOTE\nThe flag found previously \
                {validation_token} is false and is not the right response. Find another way."

        # Safely extract detailed_summary from threat_model_data
        # When supervisor fails, detailed_summary may not be set
        detailed_summary = threat_model_data.get('detailed_summary', '')
        if not detailed_summary:
            # Fallback to last_output if available
            last_output = threat_model_data.get('last_output', '')
            if isinstance(last_output, dict):
                detailed_summary = last_output.get('detailed_summary', str(last_output))
            else:
                detailed_summary = str(last_output) if last_output else "No threat model data available"

        plan, validation_token = await deadend_agent.run_exploitation(threat_model=detailed_summary, task=prompt)
        if validation_token and len(validation_token) > 1 and eval_metadata.solution:
            solved = (validation_token == eval_metadata.solution)
            print(f"Validation check: expected={eval_metadata.solution}, got={validation_token}, solved={solved}")
        else:
            print("Validation check: FLAG NOT FOUND.")
    # Render and persist metrics for the end user.
    metrics_md = metrics_to_markdown(global_metrics, eval_metadata.model_dump())
    metrics_json = metrics_to_json(global_metrics, eval_metadata.model_dump())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create .cache/deadend/eval_metrics directory if it doesn't exist
    metrics_dir = Path.home() / ".cache" / "deadend" / "eval_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # Write both markdown and JSON files
    metrics_md_path = metrics_dir / f"deadend_metrics_{timestamp}.md"
    metrics_json_path = metrics_dir / f"deadend_metrics_{timestamp}.json"

    metrics_md_path.write_text(metrics_md, encoding="utf-8")
    metrics_json_path.write_text(metrics_json, encoding="utf-8")

    print(f"Deadend metrics summary written to {metrics_md_path}")
    print(f"Deadend metrics JSON written to {metrics_json_path}")
    print(metrics_md)
    # case if not guided, i.e. not using subtasks
    # if not guided:
    #     judge_output = await workflow_agent.start_workflow(
    #         prompt,
    #         target=target_host,
    #         validation_type=eval_metadata.validation_type,
    #         validation_format=eval_metadata.validation_format
    #     )
    # else:
    #     for subtask in eval_metadata.subtasks:
    #         subtask_prompt = f"{subtask.subtask}\n{subtask.question}\n{subtask.hints}"
    #         judge_output = await workflow_agent.start_workflow(
    #             subtask_prompt,
    #             target=target_host,
    #             validation_type=eval_metadata.validation_type,
    #             validation_format=eval_metadata.validation_format
    #         )


# async def eval_all_models(models: list[AIModel], evaluators: list[Evaluator], eval_metadata_path: str, output_report: str):
#     """
#     Eval function all models
#     """
#     for model in models:
#         await eval_agent(
#             model=model,
#             # evaluators=evaluators,
#             eval_metadata_path=eval_metadata_path,
#             output_report=output_report
#         )