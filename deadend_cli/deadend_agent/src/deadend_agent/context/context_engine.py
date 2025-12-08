# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Context engine for managing workflow state and task coordination.

This module provides context management functionality for security research
workflows, including task tracking, workflow state management, and agent
routing based on current context and progress.
"""

from heapq import heappush
import json
import uuid
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING

import tiktoken

from deadend_agent.models import AIModel
from deadend_agent.utils.structures import Task, TaskPlanner

if TYPE_CHECKING:
    from deadend_agent.agents import RouterOutput
    from deadend_agent.agents.reporter import ReporterAgent


def num_tokens_from_string(string: str, encoding_name: str = "o200k_base") -> int:
    """Returns the number of tokens in a text string using tiktoken."""
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(string))

class ContextEngine:
    """Context engine for managing workflow state and task coordination.
    
    This class provides context management functionality for security research
    workflows, including task tracking, workflow state management, and agent
    routing based on current context and progress. It also persists context
    to text files for session management and recovery.
    
    Attributes:
        workflow_context (str): The complete context from the start of the workflow.
        tasks (Dict[int, Task]): Dictionary mapping task indices to Task objects.
        next_agent (str): Name of the next agent to be executed.
        target (str): Information about the current target being analyzed.
        assets (Dict[str, str]): Dictionary mapping asset names to their content.
        session_id (uuid.UUID): Unique identifier for this workflow session.
        context_file_path (Path): Path to the text context file for this session.
    """
    workflow_context: str = ""
    # Defines the whole context from the start of the workflow
    tasks: Dict[TaskPlanner, list]
    # Defines the new last tasks set
    next_agent: str
    # Name of the next agent
    target: str
    # Information about the target
    assets: Dict[str, str]
    # Assets information
    session_id: uuid.UUID | None
    # Unique session identifier
    context_file_path: Path
    # Path to the text context file
    model: AIModel
    # Adding AI model for summarization if input tokens too long
    def __init__(self, model: AIModel, session_id: uuid.UUID | None = None) -> None:
        """Initialize the ContextEngine with empty state.
        
        Args:
            session_id: Optional UUID for the session. If not provided, a new one is generated.
        
        Sets up the context engine with empty dictionaries for tasks and assets,
        initializes the next_agent to an empty string, and creates the context file path.
        """
        self.session_id = session_id
        self.root_goal = ""
        self.tasks = {}
        self.next_agent = ""
        self.assets = {}
        self.target = ""
        self.workflow_context = ""
        self.final_goal = ""
        self.model = model

        # Create context directory if it doesn't exist
        context_dir = Path.home() / ".cache" / "deadend" / "sessions" / str(self.session_id)
        context_dir.mkdir(parents=True, exist_ok=True)

        # Set context file path
        self.context_file_path = context_dir / "context.txt"

        # Initialize context file with empty structure
        self._initialize_context_file()

    def set_root_task(self, root: str):
        self.final_goal = root

    def add_tasks(self, parent_task: TaskPlanner | None,  tasks: List[TaskPlanner]):
        if parent_task is None:
            for task in tasks:
                self.tasks[task] = []

        else:
            nested_tasks = {}
            for task in tasks:
                nested_tasks[task] = {}
            self.tasks[parent_task] = nested_tasks
    
    def get_tasks(self, depth: int = 0) -> str:
        """Return a concise textual summary of planner tasks for the given depth.

        The summary includes tasks at the requested depth and recursively nests
        any available child depths. This string is later injected into prompts,
        so it favors short, high-signal lines.
        """
        header = "[planner tasks]"
        depth_line = f"Depth: {depth}"

        goal_line = f"Final goal: {self.final_goal}" if self.final_goal else "Final goal: No goal recorded."
        tasks_context = f"""{header} {depth_line}
{goal_line}
"""
        if not self.tasks:
            return tasks_context
        tasks_lines = ""
        for task, children in enumerate(self.tasks.items()):
            task_line = f"""{task} :\n
        {children}
"""
            tasks_lines += "\n" + task_line
        tasks_context += "\n" + tasks_lines
        return tasks_context


    def set_tasks(self, tasks: List[Task]) -> None:
        """Set the current tasks and update workflow context.
        
        Args:
            tasks (List[Task]): List of Task objects to be set as current tasks.
        
        Updates the workflow context with the new tasks and stores them
        in the tasks dictionary with enumerated indices. Also saves to text file.
        """
        self.workflow_context += f"""\n
[planner tasks]
{str(tasks)}
"""
        self.tasks = dict(enumerate(task for task in tasks))
        self._append_to_context_file("[ai agent]", f"Planner agent new tasks:\n{str(tasks)}")

    def set_target(self, target: str) -> None:
        """Set the current target and update workflow context.
        
        Args:
            target (str): Information about the new target to be analyzed.
        
        Updates the workflow context with the new target information
        and stores it in the target attribute. Also saves to text file.
        """
        self.workflow_context += f"""\n
[target]
{target}
"""
        self.target = target
        self._append_to_context_file("[user input]", f"Target: {target}")

    async def get_all_context(self) -> str:
        """Get the complete workflow context.
        
        Returns:
            str: The complete workflow context string containing all
                 accumulated information from the workflow execution.
        """
        # Optionally summarize if context is too large before returning it.
        tokens = await self.maybe_summarize_context()
        print(tokens)
        return self.workflow_context

    async def maybe_summarize_context(
        self,
        token_threshold: int = 200_000,
        encoding_name: str = "o200k_base",
    ) -> int:
        """Summarize workflow context with the reporter agent if token count is high.

        This helper estimates the token count of ``workflow_context`` using a simple
        whitespace split. When the count exceeds ``token_threshold``, it uses the
        provided reporter agent to summarize and overwrite the current context.

        Args:
            reporter_agent: An initialized ``ReporterAgent`` instance that will be
                used to summarize the context.
            token_threshold: Maximum allowed token count before summarization is
                triggered. Defaults to 200,000.

        Returns:
            int: The estimated token count before any summarization took place.
        """
        # Use tiktoken to estimate token count for the current context.
        current_context = self.workflow_context
        token_count = num_tokens_from_string(current_context, encoding_name)

        if token_count > token_threshold:
            # Import here to avoid a hard import cycle at module import time.
            from deadend_agent.agents.reporter import ReporterAgent

            reporter_agent = ReporterAgent(
                model=self.model,
                deps_type=None,
                tools=[],
                validation_format="New context with the relevant information",
                validation_type="Summarize context",
            )
            # ReporterAgent.summarize_context will update workflow_context via
            # ContextEngine.set_new_workflow, so no direct assignment is needed.
            result = await reporter_agent.summarize_context(self)
            self.workflow_context = result.output
        return token_count

    def add_next_agent(self, router_output: "RouterOutput") -> None:
        """Add router output information and set the next agent.
        
        Args:
            router_output (RouterOutput): The output from the router agent
                                         containing the next agent name and
                                         routing information.
        
        Updates the next_agent attribute and adds the router output
        to the workflow context. Also saves to text file.
        """
        self.next_agent = router_output.next_agent_name
        self.workflow_context  += f"""\n
[router agent]
{str(router_output)}
"""
        self._append_to_context_file("[ai agent]", f"Router agent: {str(router_output)}")
    def add_not_found_agent(self, agent_name: str) -> None:
        """Add information about a not found agent to the workflow context.
        
        Args:
            agent_name (str): The name of the agent that was not found.
        
        Adds a message to the workflow context indicating that the
        specified agent was not found. Also saves to text file.
        """
        self.workflow_context += f"""
[agent not found {agent_name}]\n
"""
        self._append_to_context_file("[ai agent]", f"Not found agent name: {agent_name}")
    def add_agent_response(self, response: str, agent_name: str = "") -> None:
        """Add an agent response to the workflow context.
        
        Args:
            response (str): The response from an agent to be added to
                           the workflow context.
        
        Appends the agent response to the workflow context with
        appropriate formatting. Also saves to text file.
        """
        self.workflow_context += f"""
{response}
"""
        self._append_to_context_file("[ai agent]", f"Agent response:\n{response}")
    def add_asset_file(self, file_name: str, file_content: str) -> None:
        """Add an asset file to the assets dictionary.
        
        Args:
            file_name (str): The name of the asset file.
            file_content (str): The content of the asset file.
        
        Stores the asset file in the assets dictionary for later
        inclusion in the workflow context. Also saves to text file.
        """
        self.assets[file_name] = file_content
        self._append_to_context_file("[Tool use: file_asset]", f"Added asset file: {file_name}")

    def add_assets_to_context(self) -> None:
        """Add all stored assets to the workflow context.
        
        Iterates through all assets in the assets dictionary and
        adds them to the workflow context with appropriate formatting.
        Each asset is added with a filename header followed by its content.
        Also saves to text file.
        """
        for asset_name, asset_content in self.assets.items():
            self.workflow_context += f"""
[filename {asset_name}]
{asset_content}
"""
            self._append_to_context_file("[Tool use: file_asset]", f"Asset file: {asset_name}\n{asset_content}")

    def _initialize_context_file(self) -> None:
        """Initialize the context file with session information.
        
        Checks if a context file already exists and loads its content into
        workflow_context. If no file exists, creates a new text file with
        session metadata and initial structure.
        
        Raises:
            OSError: If the file cannot be written.
        """
        # Check if context file already exists
        if self.context_file_path.exists():
            # Load existing context into workflow_context
            if self.load_context_from_file():
                return  # Successfully loaded existing context

        # If no existing file or loading failed, create new file
        try:
            with open(self.context_file_path, 'w', encoding='utf-8') as f:
                f.write("\n")

        except OSError as e:
            # Log error but don't raise to avoid breaking workflow
            print(f"Warning: Could not initialize context file: {e}")

    def _append_to_context_file(self, section: str, content: str) -> None:
        """Append content to the context file with proper formatting.
        
        Args:
            section: The section header (e.g., "[user input]", "[ai agent]")
            content: The content to append
        
        Raises:
            OSError: If the file cannot be written.
        """
        try:
            with open(self.context_file_path, 'a', encoding='utf-8') as f:
                f.write(f"{section}\n")
                f.write(f"{content}\n\n")

        except OSError as e:
            # Log error but don't raise to avoid breaking workflow
            print(f"Warning: Could not append to context file: {e}")

    def load_context_from_file(self) -> bool:
        """Load context from the text file.
        
        Returns:
            bool: True if context was successfully loaded, False otherwise.
        
        Raises:
            OSError: If the file cannot be read.
        """
        try:
            if not self.context_file_path.exists():
                return False

            with open(self.context_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract session information from the file
            lines = content.split('\n')
            for line in lines:
                if line.startswith('Target:'):
                    self.target = line.replace('Target:', '').strip()
                elif line.startswith('='):
                    # End of header section
                    break

            # Store the full content as workflow context
            self.workflow_context = content

            return True

        except OSError as e:
            print(f"Warning: Could not load context from file: {e}")
            return False

    def add_tool_response(self, tool_name: str = "", response: str = "") -> None:
        """Add a tool response to the context file.
        
        Args:
            tool_name (str): The name of the tool that was used.
            response (str): The response from the tool.
        
        Appends the tool response to the context file with proper formatting.
        """
        self.workflow_context += f"""\\n\n[Tool response{tool_name}]\\n\n{response}\n"""
        self._append_to_context_file(f"[Tool use: {tool_name}]", response)

    def set_new_workflow(self, new_context: str) -> None:
        """Set a new workflow with the provided context string.
        
        Args:
            new_context (str): The new context string for the workflow.
        
        Replaces the current workflow context with the new context string.
        """
        self.workflow_context = new_context

    def get_context_file_path(self) -> Path:
        """Get the path to the context file.
        
        Returns:
            Path: The path to the text context file for this session.
        """
        return self.context_file_path

    def reset(self, clear_file: bool = False) -> None:
        """Reset the context engine to its initial empty state.
        
        Args:
            clear_file: If True, also clears the context file. If False (default),
                       only resets in-memory state, preserving the file.
        
        Resets all workflow state including:
        - workflow_context: Cleared to empty string
        - tasks: Cleared to empty dictionary
        - next_agent: Cleared to empty string
        - target: Cleared to empty string
        - assets: Cleared to empty dictionary
        - root_goal: Cleared to empty string
        - final_goal: Cleared to empty string
        """
        self.workflow_context = ""
        self.tasks = {}
        self.next_agent = ""
        self.target = ""
        self.assets = {}
        self.root_goal = ""
        self.final_goal = ""
        
        if clear_file:
            # Clear the context file
            try:
                with open(self.context_file_path, 'w', encoding='utf-8') as f:
                    f.write("\n")
            except OSError as e:
                print(f"Warning: Could not clear context file: {e}")

    def _read_last_lines_from_jsonl(self, file_path: Path, num_lines: int = 200) -> List[dict]:
        """Read the last N lines from a JSONL file.
        
        Handles both single-line and pretty-printed (multi-line) JSON entries.
        
        Args:
            file_path: Path to the JSONL file
            num_lines: Number of lines to read from the end (default: 200)
            
        Returns:
            List[dict]: List of parsed JSON objects from the last N lines
        """
        if not file_path.exists():
            return []

        try:
            # Read all lines
            with open(file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()

            # Read more lines than requested to ensure we get complete entries
            # (pretty-printed JSON may span multiple lines)
            # Then we'll take the last N complete entries
            lines_to_read = min(num_lines * 2, len(all_lines))
            last_lines = all_lines[-lines_to_read:] if len(all_lines) > lines_to_read else all_lines

            # Parse JSON entries (handling both single-line and multi-line pretty-printed JSON)
            parsed_entries = []
            current_entry = []
            brace_count = 0

            for line in last_lines:
                stripped = line.strip()
                if not stripped:
                    continue
                
                # Count braces to detect complete JSON objects
                brace_count += stripped.count('{') - stripped.count('}')
                current_entry.append(stripped)
                
                # When braces are balanced, we have a complete JSON object
                if brace_count == 0 and current_entry:
                    try:
                        entry_text = '\n'.join(current_entry)
                        parsed = json.loads(entry_text)
                        parsed_entries.append(parsed)
                    except json.JSONDecodeError as e:
                        # If parsing fails, try to extract just the content part
                        # This handles cases where pretty-printed JSON might have extra whitespace
                        try:
                            # Try to find the JSON object boundaries
                            entry_text = '\n'.join(current_entry)
                            # Remove any leading/trailing whitespace and try again
                            entry_text = entry_text.strip()
                            parsed = json.loads(entry_text)
                            parsed_entries.append(parsed)
                        except json.JSONDecodeError:
                            # Skip this entry if we can't parse it
                            print(e)
                    current_entry = []
                    brace_count = 0
            
            # Handle any remaining entry (incomplete at end of file)
            if current_entry and brace_count == 0:
                try:
                    entry_text = '\n'.join(current_entry)
                    parsed = json.loads(entry_text)
                    parsed_entries.append(parsed)
                except json.JSONDecodeError:
                    pass
            
            # Return the last N entries (or all if we have fewer)
            return parsed_entries[-num_lines:] if len(parsed_entries) > num_lines else parsed_entries
            
        except Exception as e:
            print(f"Warning: Could not read JSONL file {file_path}: {e}")
            return []

    def _get_session_directory(self, session_key: str | None = None) -> Path | None:
        """Determine the session directory path.
        
        Args:
            session_key: Optional session key (e.g., "host_port"). If not provided,
                        will try to extract from target or use session_id.
        
        Returns:
            Path to the session directory, or None if it cannot be determined.
        """
        if session_key:
            return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_key
        elif self.target:
            # Try to extract host and port from target
            try:
                from deadend_agent.tools.browser_automation.http_parser import extract_host_port
                host, port = extract_host_port(target_host=self.target)
                session_key = f"{host}_{port}"
                return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_key
            except Exception:
                # Fallback to using session_id if target parsing fails
                if self.session_id:
                    return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / str(self.session_id)
                else:
                    return None
        elif self.session_id:
            return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / str(self.session_id)
        else:
            return None

