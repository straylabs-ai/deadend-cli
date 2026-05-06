# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Evaluation framework for AI agent performance and security research.

This module provides evaluation functionality for testing AI agent performance,
security research capabilities, and workflow effectiveness using various
evaluation metrics and testing scenarios.
"""
from deadend_agent.agents import AgentOutput

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
import docker
from pydantic import BaseModel, Field
from deadend_agent import (
    SqliteRagConnector,
    Sandbox,
    DeadEndAgent,
)
from deadend_agent.config.settings import Config, ModelSpec
from deadend_agent.models.registry import EmbedderClient
from deadend_agent.constants import CACHE_METRICS_PATH
from deadend_agent.utils.network import deterministic_session_id
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
        model: ModelSpec,
        embedder_client: EmbedderClient,
        # evaluators: list[Evaluator],
        code_indexer_db: SqliteRagConnector,
        sandbox: Sandbox | None,
        eval_metadata: EvalMetadata,
        hard_prompt: bool,
        # choosing between hard and soft prompt
        with_code_indexing: bool,
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
        'requester': (
            "Agent specialized in quick targeted HTTP testing. Capable of handling "
            "authentication (session and token) and exploring APIs and websites. "
            "Best default for simple requests, auth checks, individual endpoints, "
            "and lightweight payload validation. Should NOT be used for automation "
            "tasks such as fuzzing, repetitive loops, or repeated exploit attempts; "
            "use python_interpreter for those tasks instead."
        ),
        'python_interpreter': (
            "Agent specialized in generating code and running it safely in a "
            "sandboxed webassembly. Best for fuzzing, repeated exploit attempts, "
            "sending many requests, parameter testing, generating testing exploits, "
            "and other repetitive or stateful security testing operations. Use this "
            "agent for tasks that need automation, loops, or multiple iterations."
        ),
        'shell': (
            "Agent that gives access to a terminal bash shell for CLI tooling. "
            "Use it for curl when exact request control is required and for external "
            "security tools such as ffuf, gobuster, sqlmap, or nmap. DO NOT have "
            "access to target source code."
        ),
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
    local_agent_id = Config.get_local_agent_id()
    embedding_session_id = deterministic_session_id(eval_metadata.target_host or "localhost")
    deadend_agent = DeadEndAgent(
        session_id=session_id,
        embedding_session_id=embedding_session_id,
        model=model,
        available_agents=generic_agents,
        max_depth=2,
        agents_storage_root=Config.agents_storage_root,
        local_agent_id=local_agent_id,
        workspace_root=str(Path.cwd().resolve())
    )
    # Set challenge name for trace file naming
    deadend_agent.challenge_name = eval_metadata.name

    if with_code_indexing:
        deadend_agent.init_webtarget_indexer(target_host)
        web_resources_crawler = await deadend_agent.crawl_target()
        code_chunks, embed_diff = await deadend_agent.embed_target(
            embedder_client=embedder_client
        )

        if embed_diff:
            delete_files = embed_diff.get("changed_files", []) + embed_diff.get("removed_files", [])
            if delete_files:
                await code_indexer_db.delete_code_chunks_for_files(
                    files=delete_files
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
    elif deadend_agent.goal_achieved:
        print(f"Validation stopped workflow in recon phase with token={validation_token}")
    else:
        print("Validation check: Continuing to the exploitation phase.")

    # print(f"Plan produced is : {plan}")
    # print(f"threat model is : {threat_model_data}")

    threat_model_computed = str(threat_model_data)
    if not deadend_agent.goal_achieved:
        if len(validation_token) > 1:
            threat_model_computed += f"## Important NOTE\nThe flag found previously \
                {str(validation_token)} is false and is not the right response. Find another way."

        # Pull the summary from the structured reporter output when available.
        threat_model_output = getattr(threat_model_data, "output", threat_model_data)
        if isinstance(threat_model_output, AgentOutput):
            detailed_summary = threat_model_output.detailed_summary
        else:
            detailed_summary = str(threat_model_output)

        task_node, validation_token = await deadend_agent.run_exploitation(
            threat_model=detailed_summary,
            task=prompt,
        )
        if validation_token and len(validation_token) > 1 and eval_metadata.solution:
            solved = (validation_token == eval_metadata.solution)
            print(f"Validation check: expected={eval_metadata.solution}, got={validation_token}, solved={solved}")
        elif deadend_agent.goal_achieved:
            print(f"Validation stopped workflow in exploitation phase with token={validation_token}")
        else:
            print("Validation check: FLAG NOT FOUND.")
    # Render and persist metrics for the end user.
    metrics_md = metrics_to_markdown(global_metrics, eval_metadata.model_dump())
    metrics_json = metrics_to_json(global_metrics, eval_metadata.model_dump())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    CACHE_METRICS_PATH.mkdir(parents=True, exist_ok=True)

    # Write both markdown and JSON files
    metrics_md_path = CACHE_METRICS_PATH / f"deadend_metrics_{timestamp}.md"
    metrics_json_path = CACHE_METRICS_PATH / f"deadend_metrics_{timestamp}.json"

    metrics_md_path.write_text(metrics_md, encoding="utf-8")
    metrics_json_path.write_text(metrics_json, encoding="utf-8")

    print(f"Deadend metrics summary written to {metrics_md_path}")
    print(f"Deadend metrics JSON written to {metrics_json_path}")
    print(metrics_md)
