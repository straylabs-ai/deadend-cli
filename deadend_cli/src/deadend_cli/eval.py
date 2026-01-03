# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""CLI evaluation interface for testing AI agent performance.

This module provides a command-line interface for running evaluations,
testing AI agent performance, and assessing security research capabilities
through various evaluation scenarios and metrics.
"""

import json
import logfire

from rich import print as console_printer
from sqlalchemy.exc import SQLAlchemyError
from deadend_agent import Config, init_rag_database, sandbox_setup, ModelRegistry
from deadend_eval.eval import EvalMetadata, eval_deadend_agent

async def eval_interface(
        config: Config,
        eval_metadata_file: str,
        providers: list[str],
        guided: bool,
    ):
    """Run evaluation interface for testing AI agent performance.

    This function orchestrates the complete evaluation workflow by:
    1. Loading and parsing evaluation metadata from a JSON file
    2. Initializing the model registry and verifying model availability
    3. Setting up the RAG (Retrieval-Augmented Generation) database for code indexing
    4. Creating and configuring a sandbox environment for isolated execution
    5. Configuring monitoring and instrumentation
    6. Executing the evaluation agent with all required components

    Args:
        config: Configuration object containing database URLs, model settings,
            and other runtime configuration.
        eval_metadata_file: Path to the JSON file containing evaluation metadata,
            including evaluation steps, target information, and asset paths.
        providers: List of model provider names to use for evaluation.
            The first provider in the list will be used for the evaluation.
        guided: Whether to run the evaluation in guided mode, which may provide
            additional prompts or step-by-step guidance during execution.

    Raises:
        RuntimeError: If no language model is configured in the model registry.
            Suggests running `deadend init` to configure models.
        SystemExit: If the vector database cannot be accessed (SQLAlchemyError
            or OSError) or if the sandbox manager cannot be started (RuntimeError
            or OSError).

    Note:
        The function automatically:
        - Enables code indexing and knowledge base features
        - Configures context engine for enhanced agent capabilities
        - Disables human intervention for automated evaluation
        - Outputs evaluation reports to the current directory
        - Uses a Kali Linux-based sandbox image for execution
    """
    # Process the evaluation metadata
    # We do so by taking the `eval_metadata_file` and processing it
    # to extract the relevant information about the evaluation and
    # the steps that needs to be taken.
    with open(eval_metadata_file, encoding="utf-8") as eval_file:
        data = json.load(eval_file)
    eval_metadata = EvalMetadata(**data)

    model_registry = ModelRegistry(config=config)
    if not model_registry.has_any_model():
        raise RuntimeError(f"No LM model configured. You can run `deadend init` to \
            initialize the required Model configuration for {providers[0]}")

    database_url = config.db_url or ""
    try:
        # Initializing the rag code indexer database
        rag_db = await init_rag_database(database_url)
    except (SQLAlchemyError, OSError) as exc:
        console_printer(f"[red]Vector DB not accessible ({exc}). Exiting now.[/red]")
        raise SystemExit(1) from exc

    try:
        sandbox_manager = sandbox_setup()
    except (RuntimeError, OSError) as exc:
        console_printer(f"[red]Sandbox manager could not be started: {exc}[/red]")
        raise SystemExit(1) from exc

    # Monitoring
    # logfire.configure(scrubbing=False)
    # logfire.instrument_pydantic_ai()

    # adding automatic build and ask prompt
    sandbox_id = sandbox_manager.create_sandbox(
        image="xoxruns/sandboxed_kali",
        volume_path=eval_metadata.assets_path
    )
    sandbox = sandbox_manager.get_sandbox(sandbox_id=sandbox_id)
    embedder_client = model_registry.get_embedder_model()
    await eval_deadend_agent(
        model=model_registry.get_model(provider=providers[0]),
        embedder_client=embedder_client,
        # evaluators=[CtfEvaluator],
        code_indexer_db=rag_db,
        sandbox=sandbox,
        eval_metadata=eval_metadata,
        guided=guided,
        human_intervention=False,
        with_context_engine=True,
        with_code_indexing=True,
        with_knowledge_base=True,
        output_report="./",
        hard_prompt=False
    )
    # for model in models:
