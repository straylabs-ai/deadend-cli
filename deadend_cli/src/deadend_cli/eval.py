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
    logfire.configure(scrubbing=False)
    logfire.instrument_pydantic_ai()

    # adding automatic build and ask prompt
    sandbox_id = sandbox_manager.create_sandbox(image="kali_deadend", volume_path=eval_metadata.assets_path)
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
    # # Configuring workflow runner
    # for model in models:
    #     workflow_runner = WorkflowRunner(model=model, config=config, )
