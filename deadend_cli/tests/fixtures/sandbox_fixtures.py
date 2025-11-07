"""Test fixtures and helpers for sandbox testing"""

import pytest
import uuid
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import docker
from src.core.sandbox.sandbox import Sandbox, SandboxStatus
from src.core.sandbox.sandbox_manager import SandboxManager


class MockContainer:
    """Mock Docker container with realistic behavior"""
    
    def __init__(self, container_id: str = None):
        self.id = container_id or f"mock_container_{uuid.uuid4().hex[:8]}"
        self.status = "running"
        self.exec_run = Mock()
        self.stop = Mock()
        self.remove = Mock()
        self.logs = Mock()
        self.attrs = {
            'Id': self.id,
            'State': {'Status': self.status},
            'Config': {'Image': 'mock:latest'}
        }
    
    def configure_exec_run(
        self, 
        commands: Dict[str, Dict[str, Any]] = None,
        default_response: Dict[str, Any] = None
    ):
        """Configure exec_run responses for specific commands"""
        if commands is None:
            commands = {}
        
        if default_response is None:
            default_response = {
                'exit_code': 0,
                'output': b'default output'
            }
        
        def side_effect(cmd, **kwargs):
            response = commands.get(cmd, default_response)
            
            # Create mock result
            result = Mock()
            result.exit_code = response.get('exit_code', 0)
            result.output = response.get('output', b'')
            
            return result
        
        self.exec_run.side_effect = side_effect
    
    def simulate_failure(self, operation: str, exception: Exception):
        """Simulate failure for specific operations"""
        if operation == 'exec_run':
            self.exec_run.side_effect = exception
        elif operation == 'stop':
            self.stop.side_effect = exception
        elif operation == 'remove':
            self.remove.side_effect = exception


class MockDockerClient:
    """Mock Docker client with container management"""
    
    def __init__(self):
        self.containers = Mock()
        self.images = Mock()
        self._containers_registry: Dict[str, MockContainer] = {}
    
    def add_container(self, container: MockContainer):
        """Add a container to the mock client"""
        self._containers_registry[container.id] = container
    
    def configure_container_run(
        self, 
        return_container: MockContainer = None,
        side_effect: Exception = None
    ):
        """Configure containers.run behavior"""
        if side_effect:
            self.containers.run.side_effect = side_effect
        else:
            container = return_container or MockContainer()
            self.add_container(container)
            self.containers.run.return_value = container
    
    def configure_container_get(self, container_map: Dict[str, MockContainer] = None):
        """Configure containers.get behavior"""
        if container_map:
            self._containers_registry.update(container_map)
        
        def get_side_effect(container_id):
            if container_id in self._containers_registry:
                return self._containers_registry[container_id]
            raise docker.errors.NotFound(f"Container {container_id} not found")
        
        self.containers.get.side_effect = get_side_effect


@pytest.fixture
def mock_docker_client():
    """Fixture providing a mock Docker client"""
    return MockDockerClient()


@pytest.fixture
def mock_container():
    """Fixture providing a mock container"""
    container = MockContainer()
    container.configure_exec_run(
        commands={
            'echo "hello"': {'exit_code': 0, 'output': b'hello\n'},
            'ls -la': {'exit_code': 0, 'output': b'total 4\ndrwxr-xr-x 2 root root 4096 Jan 1 12:00 .\n'},
            'python --version': {'exit_code': 0, 'output': b'Python 3.9.0\n'},
            'invalid_command': {'exit_code': 127, 'output': b'command not found\n'}
        }
    )
    return container


@pytest.fixture
def sandbox_with_mock_client(mock_docker_client, mock_container):
    """Fixture providing a Sandbox with mocked Docker client"""
    mock_docker_client.configure_container_run(return_container=mock_container)
    mock_docker_client.configure_container_get({mock_container.id: mock_container})
    
    sandbox = Sandbox(docker_client=mock_docker_client)
    return sandbox, mock_docker_client, mock_container


@pytest.fixture
def running_sandbox(sandbox_with_mock_client):
    """Fixture providing a running sandbox"""
    sandbox, client, container = sandbox_with_mock_client
    sandbox.start("ubuntu:latest")
    return sandbox, client, container


@pytest.fixture
def sandbox_manager_with_mocks():
    """Fixture providing SandboxManager with mocked dependencies"""
    with patch('docker.from_env') as mock_docker_env, \
         patch('src.core.sandbox.sandbox_manager.Sandbox') as mock_sandbox_class:
        
        mock_client = MockDockerClient()
        mock_docker_env.return_value = mock_client
        
        manager = SandboxManager()
        
        return manager, mock_client, mock_sandbox_class


class SandboxTestHelper:
    """Helper class for common sandbox testing operations"""
    
    @staticmethod
    def create_mock_sandbox(
        sandbox_id: uuid.UUID = None,
        status: SandboxStatus = SandboxStatus.RUNNING,
        container_id: str = None,
        execute_responses: Dict[str, Dict[str, Any]] = None
    ) -> Mock:
        """Create a mock sandbox with configurable behavior"""
        mock_sandbox = Mock(spec=Sandbox)
        mock_sandbox.id = sandbox_id or uuid.uuid4()
        mock_sandbox.status = status
        mock_sandbox.container_id = container_id or f"container_{mock_sandbox.id.hex[:8]}"
        mock_sandbox.last_command = None
        mock_sandbox.created_at = datetime.now()
        
        # Configure execute_command responses
        if execute_responses:
            def execute_side_effect(command):
                return execute_responses.get(command, {
                    "exit_code": 0,
                    "output": "default output",
                    "command": command
                })
            
            mock_sandbox.execute_command.side_effect = execute_side_effect
        else:
            mock_sandbox.execute_command.return_value = {
                "exit_code": 0,
                "output": "success",
                "command": "default"
            }
        
        return mock_sandbox
    
    @staticmethod
    def create_command_execution_matrix() -> Dict[str, Dict[str, Any]]:
        """Create a matrix of command execution scenarios for testing"""
        return {
            # Successful commands
            "echo hello": {
                "exit_code": 0,
                "output": "hello",
                "command": "echo hello",
                "streaming": False,
                "timed_out": False
            },
            "ls -la": {
                "exit_code": 0,
                "output": "total 4\n-rw-r--r-- 1 root root 0 Jan 1 12:00 file.txt",
                "command": "ls -la",
                "streaming": False,
                "timed_out": False
            },
            "python --version": {
                "exit_code": 0,
                "output": "Python 3.9.0",
                "command": "python --version",
                "streaming": False,
                "timed_out": False
            },
            
            # Error commands
            "invalid_command": {
                "exit_code": 127,
                "output": "bash: invalid_command: command not found",
                "command": "invalid_command",
                "streaming": False,
                "timed_out": False
            },
            "permission_denied": {
                "exit_code": 126,
                "output": "bash: /restricted/file: Permission denied",
                "command": "permission_denied",
                "streaming": False,
                "timed_out": False
            },
            
            # Long-running/streaming commands
            "tail -f /var/log/app.log": {
                "command": "tail -f /var/log/app.log",
                "streaming": True,
                "stream": [b"log line 1\n", b"log line 2\n", b"log line 3\n"]
            },
            
            # Timeout simulation
            "sleep 30": {
                "exit_code": -1,
                "output": "Command timed out",
                "command": "sleep 30",
                "streaming": False,
                "timed_out": True
            }
        }
    
    @staticmethod
    def assert_sandbox_state_transition(
        mock_sandbox: Mock,
        expected_states: List[SandboxStatus]
    ):
        """Assert that sandbox went through expected state transitions"""
        # This would need to be implemented based on how you track state changes
        # For now, just check final state
        if expected_states:
            assert mock_sandbox.status == expected_states[-1]
    
    @staticmethod
    def simulate_docker_errors() -> Dict[str, Exception]:
        """Create common Docker errors for testing"""
        return {
            'container_not_found': docker.errors.NotFound("Container not found"),
            'docker_daemon_error': docker.errors.DockerException("Docker daemon error"),
            'api_error': docker.errors.APIError("API call failed"),
            'image_not_found': docker.errors.ImageNotFound("Image not found"),
            'container_error': docker.errors.ContainerError(
                container="test_container",
                exit_status=1,
                command="test_command",
                image="test:image",
                stderr="Container error occurred"
            )
        }


@pytest.fixture
def sandbox_helper():
    """Fixture providing SandboxTestHelper instance"""
    return SandboxTestHelper()


@pytest.fixture
def command_matrix():
    """Fixture providing command execution test matrix"""
    return SandboxTestHelper.create_command_execution_matrix()


@pytest.fixture
def docker_errors():
    """Fixture providing Docker error scenarios"""
    return SandboxTestHelper.simulate_docker_errors()


# Parametrize fixtures for common test scenarios
@pytest.fixture(params=[
    SandboxStatus.CREATED,
    SandboxStatus.STARTING,
    SandboxStatus.RUNNING,
    SandboxStatus.STOPPED,
    SandboxStatus.ERROR
])
def sandbox_status(request):
    """Parametrized fixture for different sandbox statuses"""
    return request.param


@pytest.fixture(params=[
    "ubuntu:latest",
    "python:3.9",
    "alpine:latest",
    "node:16",
    "custom:image"
])
def docker_image(request):
    """Parametrized fixture for different Docker images"""
    return request.param


@pytest.fixture(params=[
    None,
    "/host/path:/container/path",
    "/tmp/shared:/workspace",
    "/data:/app/data:ro"
])
def volume_mount(request):
    """Parametrized fixture for different volume mount scenarios"""
    return request.param


class SandboxScenarioBuilder:
    """Builder for creating complex sandbox test scenarios"""
    
    def __init__(self):
        self.sandboxes = []
        self.execution_plan = []
        self.expected_states = {}
    
    def add_sandbox(
        self,
        name: str,
        image: str = "ubuntu:latest",
        status: SandboxStatus = SandboxStatus.RUNNING,
        commands: List[str] = None
    ):
        """Add a sandbox to the scenario"""
        commands = commands or []
        self.sandboxes.append({
            'name': name,
            'image': image,
            'status': status,
            'commands': commands
        })
        return self
    
    def add_execution_step(self, sandbox_name: str, command: str, expected_result: Dict[str, Any]):
        """Add a command execution step"""
        self.execution_plan.append({
            'sandbox': sandbox_name,
            'command': command,
            'expected': expected_result
        })
        return self
    
    def expect_final_state(self, sandbox_name: str, status: SandboxStatus):
        """Set expected final state for a sandbox"""
        self.expected_states[sandbox_name] = status
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the complete scenario"""
        return {
            'sandboxes': self.sandboxes,
            'execution_plan': self.execution_plan,
            'expected_states': self.expected_states
        }


@pytest.fixture
def scenario_builder():
    """Fixture providing SandboxScenarioBuilder"""
    return SandboxScenarioBuilder


# Performance testing helpers
class PerformanceMetrics:
    """Helper for collecting performance metrics during tests"""
    
    def __init__(self):
        self.metrics = {}
        self.start_times = {}
    
    def start_timer(self, operation: str):
        """Start timing an operation"""
        self.start_times[operation] = datetime.now()
    
    def end_timer(self, operation: str):
        """End timing an operation and record duration"""
        if operation in self.start_times:
            duration = datetime.now() - self.start_times[operation]
            self.metrics[operation] = duration.total_seconds()
            del self.start_times[operation]
    
    def get_metric(self, operation: str) -> Optional[float]:
        """Get recorded metric for operation"""
        return self.metrics.get(operation)
    
    def assert_performance(self, operation: str, max_seconds: float):
        """Assert that operation completed within time limit"""
        duration = self.get_metric(operation)
        assert duration is not None, f"No metric recorded for {operation}"
        assert duration <= max_seconds, f"{operation} took {duration}s, expected <= {max_seconds}s"


@pytest.fixture
def performance_metrics():
    """Fixture providing performance metrics collector"""
    return PerformanceMetrics()


# Integration test data
@pytest.fixture
def integration_test_data():
    """Fixture providing test data for integration tests"""
    return {
        'test_files': {
            'simple_script.py': 'print("Hello from sandbox")\n',
            'requirements.txt': 'requests==2.25.1\npytest==6.2.4\n',
            'config.json': '{"debug": true, "timeout": 30}\n'
        },
        'test_commands': [
            'echo "Integration test starting"',
            'ls -la',
            'python3 -c "import sys; print(sys.version)"',
            'cat /etc/os-release',
            'whoami',
            'pwd'
        ],
        'expected_outputs': {
            'echo "Integration test starting"': 'Integration test starting',
            'whoami': 'root',
            'pwd': '/'
        }
    }