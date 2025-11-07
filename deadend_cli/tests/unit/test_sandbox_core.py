import pytest
import uuid
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock, call
import docker.errors
from src.core.sandbox.sandbox import Sandbox, SandboxStatus


class TestSandbox:
    """Unit tests for Sandbox class"""
    
    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client"""
        client = Mock(spec=docker.DockerClient)
        client.containers = Mock()
        return client
    
    @pytest.fixture
    def mock_container(self):
        """Mock Docker container"""
        container = Mock()
        container.id = "test_container_id"
        container.exec_run = Mock()
        container.stop = Mock()
        container.remove = Mock()
        return container
    
    @pytest.fixture
    def sandbox(self, mock_docker_client):
        """Create a Sandbox instance for testing"""
        return Sandbox(docker_client=mock_docker_client)
    
    def test_sandbox_initialization(self, mock_docker_client):
        """Test sandbox initialization with default values"""
        sandbox = Sandbox(docker_client=mock_docker_client)
        
        assert isinstance(sandbox.id, uuid.UUID)
        assert sandbox.container_id is None
        assert sandbox.docker_image == ""
        assert sandbox.docker_volume == ""
        assert sandbox.status == SandboxStatus.CREATED
        assert sandbox.last_command is None
        assert isinstance(sandbox.created_at, datetime)
        assert sandbox._docker_client is mock_docker_client
    
    def test_sandbox_initialization_with_custom_data(self, mock_docker_client):
        """Test sandbox initialization with custom data"""
        custom_id = uuid.uuid4()
        custom_time = datetime(2023, 1, 1, 12, 0, 0)
        
        sandbox = Sandbox(
            docker_client=mock_docker_client,
            id=custom_id,
            docker_image="custom:image",
            docker_volume="/custom/path",
            status=SandboxStatus.RUNNING,
            created_at=custom_time
        )
        
        assert sandbox.id == custom_id
        assert sandbox.docker_image == "custom:image"
        assert sandbox.docker_volume == "/custom/path"
        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.created_at == custom_time
    
    def test_start_success_no_volume(self, sandbox, mock_docker_client, mock_container):
        """Test successful sandbox start without volume"""
        mock_docker_client.containers.run.return_value = mock_container
        
        result = sandbox.start()
        
        mock_docker_client.containers.run.assert_called_once_with(
            image="ubuntu:latest",
            volumes=None,
            runtime='runsc',
            tty=True,
            command="/bin/bash",
            detach=True,
            stdin_open=True
        )
        
        assert result is mock_container
        assert sandbox.container_id == "test_container_id"
        assert sandbox.docker_image == "ubuntu:latest"
        assert sandbox.docker_volume is None
        assert sandbox.status == SandboxStatus.RUNNING
    
    def test_start_success_with_volume(self, sandbox, mock_docker_client, mock_container):
        """Test successful sandbox start with volume"""
        mock_docker_client.containers.run.return_value = mock_container
        
        result = sandbox.start(
            container_image="python:3.9",
            volume_path="/host/path:/container/path",
            start_process="/bin/sh"
        )
        
        mock_docker_client.containers.run.assert_called_once_with(
            image="python:3.9",
            volumes=["/host/path:/container/path"],
            runtime='runsc',
            tty=True,
            command="/bin/sh",
            detach=True,
            stdin_open=True
        )
        
        assert result is mock_container
        assert sandbox.container_id == "test_container_id"
        assert sandbox.docker_image == "python:3.9"
        assert sandbox.docker_volume == "/host/path:/container/path"
        assert sandbox.status == SandboxStatus.RUNNING
    
    def test_start_failure(self, sandbox, mock_docker_client):
        """Test sandbox start failure"""
        mock_docker_client.containers.run.side_effect = docker.errors.DockerException("Docker error")
        
        with pytest.raises(docker.errors.DockerException):
            sandbox.start()
        
        assert sandbox.status == SandboxStatus.ERROR
        assert sandbox.container_id is None
    
    def test_execute_command_no_container(self, sandbox):
        """Test execute_command when container is not started"""
        with pytest.raises(ValueError, match="Container not started"):
            sandbox.execute_command("ls -la")
    
    def test_execute_command_not_running(self, sandbox):
        """Test execute_command when container is not running"""
        sandbox.container_id = "test_id"
        sandbox.status = SandboxStatus.STOPPED
        
        with pytest.raises(ValueError, match="Container not running"):
            sandbox.execute_command("ls -la")
    
    def test_execute_command_success_no_stream(self, sandbox, mock_docker_client, mock_container):
        """Test successful command execution without streaming"""
        sandbox.container_id = "test_id"
        sandbox.status = SandboxStatus.RUNNING
        
        # Mock execution result
        exec_result = Mock()
        exec_result.exit_code = 0
        exec_result.output = b"file1\nfile2\n"
        
        mock_container.exec_run.return_value = exec_result
        mock_docker_client.containers.get.return_value = mock_container
        
        result = sandbox.execute_command("ls -la", stream=False)
        
        mock_docker_client.containers.get.assert_called_once_with("test_id")
        mock_container.exec_run.assert_called_once_with(
            cmd="ls -la",
            detach=False,
            tty=True
        )
        
        expected_result = {
            "command": "ls -la",
            "exit_code": 0,
            "streaming": False,
            "stdout": "file1\nfile2\n",
            "stderr": "",
            "timed_out": False
        }
        assert result == expected_result
        assert sandbox.last_command == "ls -la"
    
    def test_execute_command_success_with_stream(self, sandbox, mock_docker_client, mock_container):
        """Test successful command execution with streaming"""
        sandbox.container_id = "test_id"
        sandbox.status = SandboxStatus.RUNNING
        
        # Mock streaming result
        exec_result = Mock()
        exec_result.output = [b"line1\n", b"line2\n"]
        
        mock_container.exec_run.return_value = exec_result
        mock_docker_client.containers.get.return_value = mock_container
        
        result = sandbox.execute_command("tail -f /var/log/app.log", stream=True)
        
        mock_container.exec_run.assert_called_once_with(
            cmd="tail -f /var/log/app.log",
            detach=False,
            tty=True,
            socket=True,
            stream=True
        )
        
        expected_result = {
            "command": "tail -f /var/log/app.log",
            "streaming": True,
            "stream": exec_result.output
        }
        assert result == expected_result
    
    def test_execute_command_no_output(self, sandbox, mock_docker_client, mock_container):
        """Test command execution with no output"""
        sandbox.container_id = "test_id"
        sandbox.status = SandboxStatus.RUNNING
        
        exec_result = Mock()
        exec_result.exit_code = 0
        exec_result.output = None
        
        mock_container.exec_run.return_value = exec_result
        mock_docker_client.containers.get.return_value = mock_container
        
        result = sandbox.execute_command("touch file.txt", stream=False)
        
        assert result["stdout"] == ""
        assert result["exit_code"] == 0
    
    def test_execute_command_failure(self, sandbox, mock_docker_client, mock_container):
        """Test command execution failure"""
        sandbox.container_id = "test_id"
        sandbox.status = SandboxStatus.RUNNING
        
        mock_container.exec_run.side_effect = Exception("Execution failed")
        mock_docker_client.containers.get.return_value = mock_container
        
        result = sandbox.execute_command("invalid_command", stream=False)
        
        expected_result = {
            "exit_code": -1,
            "output": "Error: Execution failed",
            "command": "invalid_command",
            "timed_out": False,
            "streaming": False
        }
        assert result == expected_result
    
    def test_stop_success(self, sandbox, mock_docker_client, mock_container):
        """Test successful sandbox stop"""
        sandbox.container_id = "test_id"
        mock_docker_client.containers.get.return_value = mock_container
        
        sandbox.stop()
        
        mock_docker_client.containers.get.assert_called_once_with("test_id")
        mock_container.stop.assert_called_once()
        assert sandbox.status == SandboxStatus.STOPPED
    
    def test_stop_container_not_found(self, sandbox, mock_docker_client):
        """Test stop when container is not found"""
        sandbox.container_id = "test_id"
        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        
        # Should not raise exception
        sandbox.stop()
        
        mock_docker_client.containers.get.assert_called_once_with("test_id")
    
    def test_stop_no_container(self, sandbox):
        """Test stop when no container_id is set"""
        sandbox.stop()  # Should not raise exception
    
    def test_cleanup_success(self, sandbox, mock_docker_client, mock_container):
        """Test successful sandbox cleanup"""
        sandbox.container_id = "test_id"
        mock_docker_client.containers.get.return_value = mock_container
        
        sandbox.cleanup()
        
        mock_docker_client.containers.get.assert_called_once_with("test_id")
        mock_container.remove.assert_called_once_with(force=True)
        assert sandbox.status == SandboxStatus.STOPPED
        assert sandbox.container_id is None
    
    def test_cleanup_container_not_found(self, sandbox, mock_docker_client):
        """Test cleanup when container is not found"""
        sandbox.container_id = "test_id"
        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        
        # Should not raise exception
        sandbox.cleanup()
        
        mock_docker_client.containers.get.assert_called_once_with("test_id")
    
    def test_cleanup_no_container(self, sandbox):
        """Test cleanup when no container_id is set"""
        sandbox.cleanup()  # Should not raise exception


class TestSandboxStatus:
    """Test SandboxStatus enum"""
    
    def test_sandbox_status_values(self):
        """Test that SandboxStatus has expected values"""
        assert SandboxStatus.CREATED == "created"
        assert SandboxStatus.STARTING == "starting" 
        assert SandboxStatus.RUNNING == "running"
        assert SandboxStatus.STOPPED == "stopped"
        assert SandboxStatus.ERROR == "error"
    
    def test_sandbox_status_enum_members(self):
        """Test that all expected enum members exist"""
        expected_members = {"CREATED", "STARTING", "RUNNING", "STOPPED", "ERROR"}
        actual_members = {member.name for member in SandboxStatus}
        assert actual_members == expected_members


@pytest.mark.parametrize("image,volume,process,expected_volumes", [
    ("ubuntu:latest", None, "/bin/bash", None),
    ("python:3.9", "/host:/container", "/bin/sh", ["/host:/container"]),
    ("alpine:latest", "/tmp:/workspace", "sh", ["/tmp:/workspace"]),
])
def test_start_with_different_parameters(image, volume, process, expected_volumes):
    """Test sandbox start with different parameter combinations"""
    mock_docker_client = Mock(spec=docker.DockerClient)
    mock_container = Mock()
    mock_container.id = "test_id"
    mock_docker_client.containers.run.return_value = mock_container
    
    sandbox = Sandbox(docker_client=mock_docker_client)
    
    sandbox.start(container_image=image, volume_path=volume, start_process=process)
    
    mock_docker_client.containers.run.assert_called_once_with(
        image=image,
        volumes=expected_volumes,
        runtime='runsc',
        tty=True,
        command=process,
        detach=True,
        stdin_open=True
    )