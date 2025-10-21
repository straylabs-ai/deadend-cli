# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""CLI evaluation interface for testing AI agent performance.

This module provides a command-line interface for running evaluations,
testing AI agent performance, and assessing security research capabilities
through various evaluation scenarios and metrics.
"""

import logfire
import json

from rich import print as console_printer
from deadend_sdk import Config, init_rag_database, sandbox_setup, ModelRegistry
from eval.eval import EvalMetadata, eval_agent
from eval.ctf_evaluator import CtfEvaluator

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
    with open(eval_metadata_file) as eval_file:
        data = json.load(eval_file)
    eval_metadata = EvalMetadata(**data)

    model_registry = ModelRegistry(config=config)
    # Here we try to get the registry of all the models that we sat up
    # Which means all the models configured in env file or variables
    # We aim to evaluate the same agent on multiple models.
    models = model_registry.get_all_models()

    try: 
        # Initializing the rag code indexer database
        rag_db = await init_rag_database(config.db_url)
    except Exception: # TODO: This section need to be handled in a better way
        console_printer.print("Vector DB not accessible. Exiting now.")
        exit()
    
    try:
        sandbox_manager = sandbox_setup()
    except Exception as e: 
        console_printer.print(f"Sandbox manager could not be started : {e}")
        exit()
    
    # Monitoring 
    logfire.configure(scrubbing=False)
    logfire.instrument_pydantic_ai()

    # adding automatic build and ask prompt 
    sandbox_id = sandbox_manager.create_sandbox(image="kali_deadend", volume_path=eval_metadata.assets_path)
    sandbox = sandbox_manager.get_sandbox(sandbox_id=sandbox_id)

    await eval_agent(
        model=model_registry.get_model(provider=providers[0]),
        # evaluators=[CtfEvaluator],
        config=config,
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
