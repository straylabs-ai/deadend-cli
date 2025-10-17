# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Docker-based sandbox for secure command execution and isolation.

This module provides a sandbox implementation using Docker containers for secure 
execution of commands. The sandbox ensures isolation and 
prevents system compromise during vulnerability testing by running commands
in isolated Docker containers.

The sandbox supports:
- Container lifecycle management (create, start, stop, cleanup)
- Secure command execution with streaming and non-streaming modes
- Volume mounting for persistent data storage
- Network isolation using Docker networks
- Error handling for Docker operations

Example:
    sandbox = Sandbox(docker_client=docker_client)
    sandbox.start("ubuntu:20.04", "path/to/challenge")
    result = sandbox.execute_command("ls -la")
    sandbox.stop()
    sandbox.cleanup()

Note:
    This sandbox implementation is designed for security research and pentesting,
    providing isolation from the host system to prevent accidental damage.
"""
from enum import Enum
from datetime import datetime
import docker
from docker.errors import ImageNotFound, NotFound
import docker.errors
import shlex
import threading
import time
from typing import Optional, Union

from pydantic import BaseModel, Field


class CommandTimeoutError(Exception):
    """Exception raised when a command execution times out."""
    def __init__(self, message="Command execution timed out"):
        super().__init__(message)


class SandboxStatus(str, Enum):
    """Enumeration of possible sandbox container states.
    
    Defines the lifecycle states of a sandbox container, used to track
    the current operational status and prevent invalid operations.
    
    Attributes:
        CREATED: Container has been initialized but not started
        STARTING: Container is in the process of starting up
        RUNNING: Container is active and ready to execute commands
        STOPPED: Container has been stopped but not removed
        ERROR: Container encountered an error during operation
    """
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"

class Sandbox(BaseModel):
    """Docker-based sandbox container for secure command execution.
    
    A Pydantic model that manages Docker container lifecycle and provides
    secure execution environment for security research commands. The sandbox
    uses Docker containers with optional gVisor runtime (runsc) for enhanced
    isolation and security.
    
    Attributes:
        container_id: Unique Docker container identifier
        docker_image: Docker image name/tag used for the container
        fs_volume: Path to mounted filesystem volume for persistent data
        status: Current operational status of the container
        last_command: Most recently executed command for tracking
        created_at: Timestamp when the sandbox was created
        _docker_client: Private Docker client instance for API interactions
        
    Example:
        >>> docker_client = docker.from_env()
        >>> sandbox = Sandbox(docker_client=docker_client)
        >>> sandbox.start("ubuntu:20.04", "/path/to/challenge")
        >>> result = sandbox.execute_command("ls -la", stream=False)
        >>> sandbox.stop()
        >>> sandbox.cleanup()
        
    Note:
        The sandbox requires a valid Docker client and appropriate permissions
        to create and manage containers. Volume mounting is read-only by default
        for security purposes.
    """
    container_id : str | None = None
    docker_image: str = ""
    fs_volume: str = ""
    status: SandboxStatus = SandboxStatus.CREATED
    last_command: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    _docker_client: docker.DockerClient # = Field(exclude=True, default=None)

    class Config:
        arbitrary_types_allowed = True
        use_enum_values = True

    def __init__(self, docker_client: docker.DockerClient, **data):
        """Initialize the Sandbox with a Docker client.
        
        Args:
            docker_client: Docker client instance for container operations
            **data: Additional Pydantic model data (container_id, docker_image, etc.)
            
        Raises:
            ValidationError: If provided data doesn't match expected schema
        """
        super().__init__(**data)
        self._docker_client = docker_client

    def start(
        self,
        container_image: str,
        volume_path: str | None = None, 
        start_process: str = "/bin/bash",
        network_name: str = "host"
    ):
        """Start the sandbox container with specified image and configuration.
        
        Creates and starts a Docker container using the provided image, mounting
        optional volumes and setting up network isolation. The container runs
        in detached mode with TTY and stdin enabled for interactive commands.
        
        Args:
            container_image: Docker image name/tag to use (e.g., "ubuntu:20.04")
            volume_path: Path to mount as read-only volume at `/challenge`
            start_process: Initial command to run in container (default: "/bin/bash")
            network_name: Docker network name to connect the container to (default: "shared_net")
            
        Returns:
            docker.models.containers.Container: The created and started container
            
        Raises:
            ImageNotFound: If the specified Docker image doesn't exist
            NotFound: If Docker resources are not found during operation
            Exception: For any other Docker API errors
            
        Note:
            - Container connects to the specified network name
            - Volume mounts are read-only by default for security
            - Container status is automatically updated on success/failure
        """
        self.fs_volume = volume_path
        try:
            self.status = SandboxStatus.RUNNING
            image = self._docker_client.images.get(container_image)

            print(f"[INFO] Creating container on network: {network_name}")
            
            # Add host.docker.internal for host access when using non-host networks
            extra_hosts = None
            if network_name != "host":
                extra_hosts = {
                    "host.docker.internal": "host-gateway"  # Maps to the host machine
                }
                print("[INFO] Adding host.docker.internal alias for host access")
                
            container = self._docker_client.containers.run(
                image=image,
                volumes={
                    self.fs_volume: {'bind':'/challenge', 'mode':'ro'}
                }, 
                # runtime='runsc',
                network=network_name,
                extra_hosts=extra_hosts,
                tty=True,
                command=start_process,
                detach=True,
                stdin_open=True
            )
            
            print(f"[SUCCESS] Container created on network: {network_name}")
            if network_name == "host":
                print("[INFO] Container has direct host network access")
            else:
                print("[INFO] Use 'host.docker.internal' to access host services from within container")
                
            print(container)
            self.container_id = container.id 
            self.docker_image = container_image
            
            self.status = SandboxStatus.RUNNING
            return container
        except ImageNotFound as exc:
            print(f"Error: Image not found {container_image}")
            raise ImageNotFound from exc
        except NotFound as exc:
            print(f"Error: {exc.explanation}")
            raise NotFound from exc
        except Exception as exc:
            self.status = SandboxStatus.ERROR
            print(f"Error starting container: {exc}")
            raise exc
        
    def execute_command(
        self,
        command: str,
        stream: bool = True,
        timeout_seconds: Optional[int] = None,
        shell_execution: bool = True
    ):
        """Execute a command in the sandbox container with proper shell handling and timeout.
        
        Runs the specified command inside the running container and returns the output.
        Supports both streaming and non-streaming execution modes with timeout functionality.
        
        Args:
            command: Command string to execute (e.g., "ls -la", "curl 'http://example.com'")
            stream: If True, returns streaming output; if False, returns complete output
            timeout_seconds: Maximum execution time in seconds (None for no timeout)
            shell_execution: If True, execute via shell with proper escaping; if False, direct exec
            
        Returns:
            dict: Command execution results containing:
                - command: The executed command string
                - exit_code: Process exit code (non-streaming mode only)
                - stdout: Standard output as string (non-streaming mode only)
                - stderr: Standard error as string (non-streaming mode only)
                - streaming: Boolean indicating if output is streamed
                - stream: Raw stream object (streaming mode only)
                - timed_out: True if command timed out
                - execution_time: Time taken to execute the command
                
        Raises:
            ValueError: If container is not started or not in RUNNING status
            CommandTimeoutError: If command execution exceeds timeout
            
        Example:
            >>> # Basic execution
            >>> result = sandbox.execute_command("ls -la", stream=False)
            >>> print(result['stdout'])
            
            >>> # With timeout and shell quotes
            >>> result = sandbox.execute_command('curl "http://example.com"', timeout_seconds=30)
            >>> print(result['stdout'])
            
            >>> # Streaming mode with timeout
            >>> result = sandbox.execute_command("tail -f /var/log/syslog", timeout_seconds=60)
            >>> for chunk in result['stream']:
            ...     print(chunk.decode())
        """
        start_time = time.time()
        
        if not self.container_id:
            raise ValueError("Container not started")
        if self.status != SandboxStatus.RUNNING:
            raise ValueError(f"Container not running (status: {self.status})")

        container = self._docker_client.containers.get(self.container_id)
        self.last_command = command
        
        # Debug: Check container state and responsiveness
        try:
            container_status = container.status
            print(f"[DEBUG] Container status: {container_status}")
            
            # Test basic container responsiveness with a simple command
            health_check = container.exec_run(["/bin/bash", "-c", "echo 'health_check'"])
            print(f"[DEBUG] Health check exit code: {health_check.exit_code}")
        except Exception as health_exc:
            print(f"[DEBUG] Container health check failed: {health_exc}")

        # Prepare command for execution
        if shell_execution:
            # Use shell execution with proper escaping for complex commands
            # Wrap in bash -c to handle shell features like pipes, redirects, quotes
            shell_command = ["/bin/bash", "-c", command]
        else:
            # Use shlex for proper argument parsing without shell interpretation
            shell_command = shlex.split(command)

        try:
            # Debug: Log the exact command being executed
            print(f"[DEBUG] Executing command: {' '.join(shell_command)}")
            print(f"[DEBUG] Stream mode: {stream}, Timeout: {timeout_seconds}")
            
            if timeout_seconds:
                # Use threading for timeout implementation
                result = self._execute_with_timeout(
                    container, shell_command, stream, timeout_seconds
                )
            elif stream:
                command_result = container.exec_run(
                    cmd=shell_command,
                    detach=False,
                    tty=False,  # Changed from True to False
                    socket=True,
                    stream=True,
                )
                print("[DEBUG] Streaming execution completed")
                result = {
                    "command": command,
                    "streaming": True,
                    "stream": command_result.output,
                    "timed_out": False,
                    "execution_time": time.time() - start_time
                }
            else:
                command_result = container.exec_run(
                    cmd=shell_command,
                    detach=False,
                    tty=False,  # Changed from True to False
                    demux=True
                )
                print(f"[DEBUG] Command executed, exit code: {command_result.exit_code}")
                (stdout, stderr) = command_result.output
                print(f"[DEBUG] Raw stdout length: {len(stdout) if stdout else 0}, stderr: {len(stderr) if stderr else 0}")
                result = {
                    "command": command,
                    "exit_code": command_result.exit_code,
                    "streaming": False,
                    "stdout": stdout.decode('utf-8') if stdout else "",
                    "stderr": stderr.decode('utf-8') if stderr else "",
                    "timed_out": False,
                    "execution_time": time.time() - start_time
                }
                print(f"[DEBUG] Decoded stdout length: {len(result['stdout'])}, stderr: {len(result['stderr'])}")
            
            return result

        except CommandTimeoutError:
            return {
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_seconds} seconds",
                "streaming": False,
                "timed_out": True,
                "execution_time": time.time() - start_time
            }
        except (FileNotFoundError, PermissionError, RuntimeError) as exc:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution error: {str(exc)}",
                "command": command,
                "timed_out": False,
                "streaming": False,
                "execution_time": time.time() - start_time
            }
        except (docker.errors.ContainerError, docker.errors.APIError, OSError) as exc:
            # Log docker and system errors but don't raise to maintain stability
            print(f"[ERROR] Docker/System error: {exc}")
            import traceback
            traceback.print_exc()
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"System error: {str(exc)}",
                "command": command,
                "timed_out": False,
                "streaming": False,
                "execution_time": time.time() - start_time
            }
        except Exception as exc:
            # Catch-all for any unexpected errors
            print(f"[ERROR] Unexpected error: {exc}")
            import traceback
            traceback.print_exc()
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unexpected error: {str(exc)}",
                "command": command,
                "timed_out": False,
                "streaming": False,
                "execution_time": time.time() - start_time
            }

    def _execute_with_timeout(
        self, 
        container, 
        command: Union[str, list], 
        stream: bool, 
        timeout_seconds: int
    ) -> dict:
        """Execute command with timeout support using threading."""
        result_container = {}
        exception_container = {}

        def execute_worker():
            try:
                print(f"[DEBUG TIMEOUT] Starting worker thread for command: {' '.join(command if isinstance(command, list) else [command])}")
                start_time = time.time()
                if stream:
                    command_result = container.exec_run(
                        cmd=command,
                        detach=False,
                        tty=False,  # Changed from True to False
                        socket=True,
                        stream=True,
                    )
                    print("[DEBUG TIMEOUT] Streaming command completed")

                    result_container["result"] = {
                        "command": self.last_command,
                        "streaming": True,
                        "stream": command_result.output,
                        "timed_out": False,
                        "execution_time": time.time() - start_time
                    }
                else:
                    command_result = container.exec_run(
                        cmd=command,
                        detach=False,
                        tty=False,  # Changed from True to False
                        demux=True
                    )
                    print(f"[DEBUG TIMEOUT] Command executed, exit code: {command_result.exit_code}")
                    (stdout, stderr) = command_result.output
                    print(f"[DEBUG TIMEOUT] Raw stdout length: {len(stdout) if stdout else 0}, stderr: {len(stderr) if stderr else 0}")
                    result_container["result"] = {
                        "command": self.last_command,
                        "exit_code": command_result.exit_code,
                        "streaming": False,
                        "stdout": stdout.decode('utf-8') if stdout else "",
                        "stderr": stderr.decode('utf-8') if stderr else "",
                        "timed_out": False,
                        "execution_time": time.time() - start_time
                    }
                    print(f"[DEBUG TIMEOUT] Decoded stdout length: {len(result_container['result']['stdout'])}, stderr: {len(result_container['result']['stderr'])}")
            except (docker.errors.ContainerError, docker.errors.APIError, OSError) as exc:
                print(f"[DEBUG TIMEOUT] Docker/system error in worker: {exc}")
                exception_container["exception"] = exc
            except Exception as exc:
                print(f"[DEBUG TIMEOUT] Unexpected error in execute_worker: {exc}")
                import traceback
                traceback.print_exc()
                exception_container["exception"] = exc

        thread = threading.Thread(target=execute_worker)
        thread.daemon = True
        thread.start()
        
        thread.join(timeout_seconds)
        
        if thread.is_alive():
            # Command is still running, timeout occurred
            # Docker doesn't allow killing exec_run commands directly,
            # so we return a timeout result
            return {
                "command": self.last_command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_seconds} seconds",
                "streaming": False,
                "timed_out": True,
                "execution_time": timeout_seconds
            }
        
        if "exception" in exception_container:
            raise exception_container["exception"]
        
        if "result" in result_container:
            return result_container["result"]
        
        # Fallback case
        raise RuntimeError("Command execution failed without proper result")


    def stop(self):
        """Stop the sandbox container.
        
        Gracefully stops the running container and updates the status to STOPPED.
        This method is safe to call multiple times - it will silently handle
        cases where the container is already stopped or doesn't exist.
        
        Note:
            Stopping a container does not remove it from the Docker daemon.
            Use cleanup() to remove the container completely.
            
        Side Effects:
            Updates self.status to SandboxStatus.STOPPED on successful stop
        """
        if self.container_id:
            try: 
                container = self._docker_client.containers.get(self.container_id)        
                container.stop()
                self.status = SandboxStatus.STOPPED
            except docker.errors.NotFound:
                pass

    def cleanup(self):
        """Remove the sandbox container completely.
        
        Permanently removes the container from Docker daemon using force removal.
        This method clears all container resources and resets the container_id
        to None. Safe to call multiple times or when container doesn't exist.
        
        Warning:
            This operation cannot be undone. All container data and filesystem
            changes will be lost. Make sure to extract any needed data before cleanup.
            
        Side Effects:
            - Removes container from Docker daemon
            - Resets self.container_id to None  
            - Updates self.status to SandboxStatus.STOPPED
        """
        if self.container_id:
            try:
                container = self._docker_client.containers.get(self.container_id)
                container.remove(force=True)
                self.status = SandboxStatus.STOPPED
                self.container_id = None
            except docker.errors.NotFound:
                pass

