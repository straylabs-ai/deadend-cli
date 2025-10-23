# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core data structures and models for the security research framework.

This module defines the fundamental data models, enums, and structures used
throughout the application, including command execution logs, dependency
injection containers, and task management structures.
"""

import uuid
from typing import Dict, Literal
from enum import Enum
from dataclasses import dataclass
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


from deadend_sdk.rag.db_cruds import RetrievalDatabaseConnector
from deadend_sdk.sandbox.sandbox import Sandbox

class CmdLog(BaseModel):
    """
    Represents a command execution log entry with input, output, and error streams.
    
    This model captures the complete execution context of a shell command,
    including the command input (stdin), standard output (stdout), and 
    standard error (stderr) streams.
    """
    cmd_input: str = Field(description="represents a shell's stdin", alias="stdin")
    cmd_output: str = Field(description="represents a shell's stdout", alias="stdout")
    cmd_error: str = Field(description="represents a shell's stderr", alias="stderr")

class ShellRunner:
    """
    Sandboxed shell runner for executing commands in a controlled environment.
    
    This class provides a safe way to execute shell commands within a sandbox,
    maintaining a log of all command executions including their input, output,
    and error streams. Each command execution is tracked and can be retrieved
    for analysis or debugging purposes.
    
    Attributes:
        session: Session identifier for the shell runner instance
        sandbox: Sandbox instance for secure command execution
        cmd_log: Dictionary mapping command numbers to CmdLog entries
    """
    session: str
    sandbox: Sandbox
    cmd_log: Dict[int, CmdLog]

    def __init__(self, session: str, sandbox: Sandbox):
        """
        Initialize the ShellRunner with a session and sandbox.
        
        Args:
            session: Optional session identifier for this runner instance
            sandbox: Sandbox instance for secure command execution
        """
        self.session = session
        self.sandbox = sandbox

        self.cmd_log = {}

    def run_command(self, new_cmd: str, timeout_seconds: int | None = None):
        """
        Execute a command in the sandbox and log the results.
        
        Args:
            new_cmd: The shell command to execute
            timeout_seconds: Optional timeout for command execution
        """
        result = self.sandbox.execute_command(
            new_cmd, 
            stream=False, 
            timeout_seconds=timeout_seconds,
            shell_execution=True
        )
        cmds_number = len(self.cmd_log.keys())
        print(f"command run function inside shellrunner : {result}")

        # Handle timeout cases
        if result.get("timed_out", False):
            stderr = f"Command timed out after {timeout_seconds}s: {result.get('stderr', '')}"
        else:
            stderr = result.get("stderr", "")

        self.cmd_log[cmds_number+1] = CmdLog(
            stdin=new_cmd,
            stdout=result["stdout"],
            stderr=stderr
        )
        return result 

    def get_cmd_log(self) -> Dict[int, CmdLog]:
        """
        Retrieve the complete command execution log.
        
        Returns:
            Dictionary mapping command numbers to CmdLog entries
        """
        return self.cmd_log

@dataclass
class ShellDeps:
    """
    Dependencies container for shell-related operations.
    
    This dataclass holds the shell runner instance required for
    executing shell commands in various contexts.
    
    Attributes:
        shell_runner: ShellRunner instance for command execution
    """
    shell_runner: ShellRunner

@dataclass
class WebappreconDeps:
    """
    Dependencies container for web application reconnaissance operations.
    
    This dataclass holds all the necessary components for performing
    web application reconnaissance tasks, including AI models, database
    connectors, target information, and execution environment.
    
    Attributes:
        openai: AsyncOpenAI client for AI model interactions
        rag: RetrievalDatabaseConnector for knowledge base operations
        target: Target web application URL or identifier
        shell_runner: ShellRunner for executing reconnaissance commands
        session_id: Unique session identifier for tracking operations
    """
    openai: AsyncOpenAI
    rag: RetrievalDatabaseConnector
    target: str
    shell_runner: ShellRunner
    session_id: uuid.UUID

@dataclass
class RagDeps:
    """
    Dependencies container for Retrieval-Augmented Generation (RAG) operations.
    
    This dataclass holds the essential components for RAG-based operations,
    including AI models, database connectors, and session tracking.
    
    Attributes:
        openai: AsyncOpenAI client for AI model interactions
        rag: RetrievalDatabaseConnector for knowledge base operations
        target: Target identifier for RAG operations
        session_id: Unique session identifier for tracking operations
    """
    openai: AsyncOpenAI
    rag: RetrievalDatabaseConnector
    target: str
    session_id: uuid.UUID

class HttpMethod(Enum):
    """
    Enumeration of supported HTTP methods for web requests.
    
    This enum defines the standard HTTP methods that can be used
    for making web requests, including RESTful operations and
    streaming capabilities.
    """
    GET = "GET"
    POST = "POST"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    STREAM = "STREAM"

@dataclass
class RequestStruct:
    """
    Structure representing an HTTP request with all necessary components.
    
    This dataclass encapsulates all the information needed to make
    an HTTP request, including the method, URL, headers, and content.
    
    Attributes:
        method: HTTP method to use for the request
        url: Target URL for the request
        headers: Dictionary of HTTP headers
        content: Request body content
    """
    method: HttpMethod
    url: str
    headers: Dict[str, str]
    content: str

class Task(BaseModel):
    """
    Represents a task with goal, status tracking, and output.
    
    This model defines a task structure that can be used for tracking
    the progress and results of various operations within the system.
    
    Attributes:
        goal: Description of what the task aims to accomplish
        status: Current status of the task (pending, failed, or success)
        output: Result or output produced by the task
    """
    goal: str
    status: Literal['pending', 'failed', 'success']
    output: str

class AIModel(BaseModel):
    """
    Configuration model for AI model access and authentication.
    
    This model stores the necessary information for connecting to
    and authenticating with AI model services.
    
    Attributes:
        model_name: Name or identifier of the AI model to use
        api_key: API key for authenticating with the AI service
    """
    model_name: str
    api_key: str

@dataclass
class TargetDeps:
    """
    Dependencies container for target-specific operations and analysis.
    
    This dataclass holds all the necessary components for performing
    operations on a specific target, including API specifications,
    crawl data, authentication information, and AI/RAG capabilities.
    
    Attributes:
        target: Target identifier or URL
        openapi_spec: OpenAPI specification data for the target
        path_crawl_data: Crawled path data from the target
        authentication_data: Authentication information for the target
        openai: AsyncOpenAI client for AI model interactions
        rag: RetrievalDatabaseConnector for knowledge base operations
    """
    target: str
    openapi_spec: Dict
    path_crawl_data: str
    authentication_data: str
    openai: AsyncOpenAI
    rag: RetrievalDatabaseConnector
