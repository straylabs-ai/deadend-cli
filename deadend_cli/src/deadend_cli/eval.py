# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""CLI evaluation interface for testing AI agent performance.

This module provides a command-line interface for running evaluations,
testing AI agent performance, and assessing security research capabilities
through various evaluation scenarios and metrics.
"""

import asyncio
import json
from rich import print as console_printer
from deadend_agent import Config, init_rag_session_manager, sandbox_setup, ModelRegistry
from deadend_agent.tools.browser_automation import cleanup_playwright_sessions
from deadend_eval.eval import EvalMetadata, eval_deadend_agent


def _shutdown_telemetry() -> None:
    """Flush and shutdown the global OpenTelemetry provider if available.

    This is primarily needed for eval runs where Phoenix/OTLP exporters may still
    be flushing HTTPS data while the process is exiting. Shutting the provider
    down before the event loop is torn down avoids noisy SSL transport errors at
    process exit.
    """
    try:
        from opentelemetry import trace
    except Exception:
        return

    try:
        provider = trace.get_tracer_provider()
    except Exception:
        return

    try:
        if hasattr(provider, "force_flush"):
            try:
                provider.force_flush(timeout_millis=5000)
            except TypeError:
                provider.force_flush()
    except Exception as exc:
        console_printer(f"[yellow]Telemetry force_flush failed: {exc}[/yellow]")

    try:
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception as exc:
        console_printer(f"[yellow]Telemetry shutdown failed: {exc}[/yellow]")

async def eval_interface(
        config: Config,
        eval_metadata_file: str,
        provider: str,
        model_name: str,
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
        - Enables code indexing of the target source
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
            initialize the required Model configuration for {provider}:{model_name}")

    # Initialize SQLite-based RAG
    rag_manager = init_rag_session_manager(storage_root=config.agents_storage_root)
    local_agent_id = config.get_local_agent_id()
    from deadend_agent.utils.network import deterministic_session_id
    embedding_session_id = deterministic_session_id(eval_metadata.target_host or "localhost")
    rag_db = await rag_manager.get_connector(
        agent_id=local_agent_id,
        embedding_session_id=embedding_session_id,
        target=eval_metadata.target_host or "localhost",
    )

    try:
        sandbox_manager = sandbox_setup()
    except (RuntimeError, OSError) as exc:
        console_printer(f"[red]Sandbox manager could not be started: {exc}[/red]")
        raise SystemExit(1) from exc
    try:
        sandbox_id = sandbox_manager.create_sandbox(
            image="xoxruns/sandboxed_kali",
            volume_path=eval_metadata.assets_path
        )
        sandbox = sandbox_manager.get_sandbox(sandbox_id=sandbox_id)
        embedder_client = model_registry.get_embedder_model()
        await eval_deadend_agent(
            model=model_registry.get_model(provider=provider, model_name=model_name),
            embedder_client=embedder_client,
            code_indexer_db=rag_db,
            sandbox=sandbox,
            eval_metadata=eval_metadata,
            with_code_indexing=True,
            hard_prompt=False
        )
    finally:
        # Eval-agent does not go through the normal ComponentManager shutdown path,
        # so cleanup must happen explicitly here.
        try:
            await cleanup_playwright_sessions()
        except Exception as exc:
            console_printer(f"[yellow]Playwright cleanup failed: {exc}[/yellow]")

        try:
            await rag_manager.close_all()
        except Exception as exc:
            console_printer(f"[yellow]RAG cleanup failed: {exc}[/yellow]")

        try:
            if sandbox is not None:
                sandbox.cleanup()
            elif sandbox_id is not None:
                managed_sandbox = sandbox_manager.get_sandbox(sandbox_id=sandbox_id)
                if managed_sandbox is not None:
                    managed_sandbox.cleanup()
        except Exception as exc:
            console_printer(f"[yellow]Sandbox cleanup failed: {exc}[/yellow]")

        try:
            _shutdown_telemetry()
            # Give any provider shutdown callbacks a brief chance to finish
            # before asyncio.run() closes the loop.
            await asyncio.sleep(0.1)
        except Exception as exc:
            console_printer(f"[yellow]Telemetry cleanup failed: {exc}[/yellow]")
