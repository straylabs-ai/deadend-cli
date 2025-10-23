# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Context engine for managing workflow state and task coordination.

This module provides context management functionality for security research
workflows, including task tracking, workflow state management, and agent
routing based on current context and progress.
"""

import uuid
from pathlib import Path
from typing import Dict, List, Optional
from deadend_sdk.utils.structures import Task
from deadend_sdk.agents import RouterOutput

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
    tasks: Dict[int, Task]
    # Defines the new last tasks set
    next_agent: str
    # Name of the next agent
    target: str
    # Information about the target
    assets: Dict[str, str]
    # Assets information
    session_id: uuid.UUID
    # Unique session identifier
    context_file_path: Path
    # Path to the text context file

    def __init__(self, session_id: Optional[uuid.UUID] = None) -> None:
        """Initialize the ContextEngine with empty state.
        
        Args:
            session_id: Optional UUID for the session. If not provided, a new one is generated.
        
        Sets up the context engine with empty dictionaries for tasks and assets,
        initializes the next_agent to an empty string, and creates the context file path.
        """
        self.session_id = session_id
        self.tasks = {}
        self.next_agent = ""
        self.assets = {}
        self.target = ""

        # Create context directory if it doesn't exist
        context_dir = Path.home() / ".cache" / "deadend" / "sessions" / str(self.session_id)
        context_dir.mkdir(parents=True, exist_ok=True)

        # Set context file path
        self.context_file_path = context_dir / "context.txt"

        # Initialize context file with empty structure
        self._initialize_context_file()

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

    def get_all_context(self) -> str:
        """Get the complete workflow context.
        
        Returns:
            str: The complete workflow context string containing all
                 accumulated information from the workflow execution.
        """
        return self.workflow_context

    def add_next_agent(self, router_output: RouterOutput) -> None:
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
        self.workflow_context += f"""\n
[agent not found{agent_name}]\n
"""
        self._append_to_context_file("[ai agent]", f"Not found agent name: {agent_name}")
    def add_agent_response(self, response: str) -> None:
        """Add an agent response to the workflow context.
        
        Args:
            response (str): The response from an agent to be added to
                           the workflow context.
        
        Appends the agent response to the workflow context with
        appropriate formatting. Also saves to text file.
        """
        self.workflow_context += f"""\n
[ai agent]\n
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
                f.write(f"Session ID: {self.session_id}\n")
                f.write(f"Target: {self.target}\n")
                f.write("=" * 50 + "\n\n")

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
                if line.startswith('Session ID:'):
                    # Session ID is already set in __init__
                    continue
                elif line.startswith('Target:'):
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

    def add_tool_response(self, tool_name: str, response: str) -> None:
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
