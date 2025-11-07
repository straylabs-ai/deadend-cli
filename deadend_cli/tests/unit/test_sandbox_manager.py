import pytest
import uuid
from unittest.mock import Mock, patch, MagicMock
import docker
from src.core.sandbox.sandbox_manager import SandboxManager
from src.core.sandbox.sandbox import Sandbox, SandboxStatus


class TestSandboxManager:
    """Unit tests for SandboxManager class"""
    
    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client"""
        client = Mock(spec=docker.DockerClient)
        return client
    
    @pytest.fixture
    def mock_sandbox(self):
        """Mock Sandbox instance"""
        sandbox = Mock(spec=Sandbox)
        sandbox.id = uuid.uuid4()
        sandbox.status = SandboxStatus.RUNNING
        sandbox.start = Mock()
        sandbox.stop = Mock()
        sandbox.execute_command = Mock()
        return sandbox
    
    @pytest.fixture
    def manager(self):
        """Create SandboxManager instance with mocked Docker client"""
        with patch('docker.from_env') as mock_from_env:
            mock_client = Mock(spec=docker.DockerClient)
            mock_from_env.return_value = mock_client
            
            manager = SandboxManager()
            manager.docker_client = mock_client
            return manager
    
    def test_init(self):
        """Test SandboxManager initialization"""
        with patch('docker.from_env') as mock_from_env:
            mock_client = Mock(spec=docker.DockerClient)
            mock_from_env.return_value = mock_client
            
            manager = SandboxManager()
            
            mock_from_env.assert_called_once()
            assert manager.docker_client is mock_client
            assert manager.sandboxes == {}
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_create_sandbox_default_image(self, mock_sandbox_class, manager):
        """Test creating sandbox with default image"""
        mock_sandbox_instance = Mock()
        mock_sandbox_instance.id = uuid.UUID('12345678-1234-5678-9012-123456789012')
        mock_sandbox_class.return_value = mock_sandbox_instance
        
        with patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.UUID('12345678-1234-5678-9012-123456789012')
            mock_uuid.return_value = test_uuid
            
            result = manager.create_sandbox()
            
            mock_uuid.assert_called_once()
            mock_sandbox_class.assert_called_once_with(
                docker_client=manager.docker_client,
                id=test_uuid
            )
            mock_sandbox_instance.start.assert_called_once_with(container_image="ubuntu:latest")
            
            assert result == test_uuid
            assert manager.sandboxes[test_uuid] is mock_sandbox_instance
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_create_sandbox_custom_image(self, mock_sandbox_class, manager):
        """Test creating sandbox with custom image"""
        mock_sandbox_instance = Mock()
        mock_sandbox_instance.id = uuid.UUID('12345678-1234-5678-9012-123456789012')
        mock_sandbox_class.return_value = mock_sandbox_instance
        
        with patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.UUID('12345678-1234-5678-9012-123456789012')
            mock_uuid.return_value = test_uuid
            
            result = manager.create_sandbox(image="python:3.9")
            
            mock_sandbox_instance.start.assert_called_once_with(container_image="python:3.9")
            assert result == test_uuid
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_create_sandbox_start_failure(self, mock_sandbox_class, manager):
        """Test sandbox creation when start fails"""
        mock_sandbox_instance = Mock()
        mock_sandbox_instance.start.side_effect = Exception("Failed to start container")
        mock_sandbox_class.return_value = mock_sandbox_instance
        
        with patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.UUID('12345678-1234-5678-9012-123456789012')
            mock_uuid.return_value = test_uuid
            
            with pytest.raises(Exception, match="Failed to start container"):
                sandbox_id = manager.create_sandbox()
            
            # Check that sandbox was added to registry before failure
            assert len(manager.sandboxes) == 0
    
    def test_get_sandbox_exists(self, manager):
        """Test getting existing sandbox"""
        test_uuid = uuid.uuid4()
        mock_sandbox = Mock()
        manager.sandboxes[test_uuid] = mock_sandbox
        
        result = manager.get_sandbox(test_uuid)
        
        assert result is mock_sandbox
    
    def test_get_sandbox_not_exists(self, manager):
        """Test getting non-existing sandbox"""
        test_uuid = uuid.uuid4()
        
        result = manager.get_sandbox(test_uuid)
        
        assert result is None
    
    def test_execute_in_sandbox_success(self, manager):
        """Test successful command execution in sandbox"""
        test_uuid = uuid.uuid4()
        mock_sandbox = Mock()
        mock_sandbox.status = SandboxStatus.RUNNING
        mock_sandbox.execute_command.return_value = {
            "exit_code": 0,
            "stdout": "command output",
            "stderr": "",
            "command": "ls -la"
        }
        manager.sandboxes[test_uuid] = mock_sandbox
        
        result = manager.execute_in_sandbox(test_uuid, "ls -la")
        
        mock_sandbox.execute_command.assert_called_once_with(command="ls -la")
        assert result == {
            "exit_code": 0,
            "stdout": "command output",
            "stderr": "",
            "command": "ls -la"
        }
    
    def test_execute_in_sandbox_not_found(self, manager):
        """Test execute command when sandbox not found"""
        test_uuid = uuid.uuid4()
        
        with pytest.raises(KeyError):
            manager.execute_in_sandbox(test_uuid, "ls -la")
    
    def test_execute_in_sandbox_not_running(self, manager):
        """Test execute command when sandbox is not running"""
        test_uuid = uuid.uuid4()
        mock_sandbox = Mock()
        mock_sandbox.status = SandboxStatus.STOPPED
        manager.sandboxes[test_uuid] = mock_sandbox
        
        with pytest.raises(ValueError, match="not found or status not running"):
            manager.execute_in_sandbox(test_uuid, "ls -la")
    
    def test_execute_in_sandbox_none_sandbox(self, manager):
        """Test execute command when sandbox is None"""
        test_uuid = uuid.uuid4()
        manager.sandboxes[test_uuid] = None
        
        with pytest.raises(ValueError, match="not found or status not running"):
            manager.execute_in_sandbox(test_uuid, "ls -la")
    
    def test_execute_in_sandbox_command_fails(self, manager):
        """Test execute command when sandbox command execution fails"""
        test_uuid = uuid.uuid4()
        mock_sandbox = Mock()
        mock_sandbox.status = SandboxStatus.RUNNING
        mock_sandbox.execute_command.side_effect = Exception("Command execution failed")
        manager.sandboxes[test_uuid] = mock_sandbox
        
        with pytest.raises(Exception, match="Command execution failed"):
            manager.execute_in_sandbox(test_uuid, "invalid_command")
    
    def test_stop_all_empty(self, manager):
        """Test stopping all sandboxes when none exist"""
        manager.stop_all()
        # Should not raise any exception
    
    def test_stop_all_single_sandbox(self, manager):
        """Test stopping all sandboxes with single sandbox"""
        test_uuid = uuid.uuid4()
        mock_sandbox = Mock()
        manager.sandboxes[test_uuid] = mock_sandbox
        
        manager.stop_all()
        
        mock_sandbox.stop.assert_called_once()
    
    def test_stop_all_multiple_sandboxes(self, manager):
        """Test stopping all sandboxes with multiple sandboxes"""
        test_uuid1 = uuid.uuid4()
        test_uuid2 = uuid.uuid4()
        mock_sandbox1 = Mock()
        mock_sandbox2 = Mock()
        
        manager.sandboxes[test_uuid1] = mock_sandbox1
        manager.sandboxes[test_uuid2] = mock_sandbox2
        
        manager.stop_all()
        
        mock_sandbox1.stop.assert_called_once()
        mock_sandbox2.stop.assert_called_once()
    
    def test_stop_all_with_exception(self, manager):
        """Test stopping all sandboxes when one raises exception"""
        test_uuid1 = uuid.uuid4()
        test_uuid2 = uuid.uuid4()
        mock_sandbox1 = Mock()
        mock_sandbox2 = Mock()
        
        mock_sandbox1.stop.side_effect = Exception("Stop failed")
        manager.sandboxes[test_uuid1] = mock_sandbox1
        manager.sandboxes[test_uuid2] = mock_sandbox2
        
        # Exception should propagate up
        with pytest.raises(Exception, match="Stop failed"):
            manager.stop_all()
        
        mock_sandbox1.stop.assert_called_once()
        # Second sandbox stop may or may not be called depending on order


class TestSandboxManagerIntegration:
    """Integration-style tests for SandboxManager (still using mocks but testing workflow)"""
    
    @pytest.fixture
    def manager_with_mocked_sandbox(self):
        """Create manager with mocked Sandbox class"""
        with patch('docker.from_env') as mock_from_env, \
             patch('src.core.sandbox.sandbox_manager.Sandbox') as mock_sandbox_class:
            
            mock_client = Mock(spec=docker.DockerClient)
            mock_from_env.return_value = mock_client
            
            manager = SandboxManager()
            
            return manager, mock_sandbox_class
    
    def test_create_and_execute_workflow(self, manager_with_mocked_sandbox):
        """Test complete workflow: create sandbox -> execute command -> stop"""
        manager, mock_sandbox_class = manager_with_mocked_sandbox
        
        # Setup mock sandbox
        mock_sandbox = Mock(spec=Sandbox)
        mock_sandbox.status = SandboxStatus.RUNNING
        mock_sandbox.execute_command.return_value = {"exit_code": 0, "stdout": "success", "stderr": ""}
        mock_sandbox_class.return_value = mock_sandbox
        
        with patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.uuid4()
            mock_uuid.return_value = test_uuid
            
            # Create sandbox
            sandbox_id = manager.create_sandbox("python:3.9")
            assert sandbox_id == test_uuid
            
            # Execute command
            result = manager.execute_in_sandbox(sandbox_id, "python --version")
            assert result == {"exit_code": 0, "stdout": "success", "stderr": ""}
            
            # Stop all
            manager.stop_all()
            
            # Verify calls
            mock_sandbox.start.assert_called_once_with(container_image="python:3.9")
            mock_sandbox.execute_command.assert_called_once_with(command="python --version")
            mock_sandbox.stop.assert_called_once()
    
    def test_multiple_sandboxes_workflow(self, manager_with_mocked_sandbox):
        """Test workflow with multiple sandboxes"""
        manager, mock_sandbox_class = manager_with_mocked_sandbox
        
        # Create multiple mock sandboxes
        mock_sandbox1 = Mock(spec=Sandbox)
        mock_sandbox1.status = SandboxStatus.RUNNING
        mock_sandbox1.execute_command.return_value = {"exit_code": 0, "stdout": "output1", "command": "ls"}
        
        mock_sandbox2 = Mock(spec=Sandbox)
        mock_sandbox2.status = SandboxStatus.RUNNING  
        mock_sandbox2.execute_command.return_value = {"exit_code": 0, "stdout": "output2", "command": "python --version"}
        
        mock_sandbox_class.side_effect = [mock_sandbox1, mock_sandbox2]
        
        with patch('uuid.uuid4') as mock_uuid:
            uuid1 = uuid.UUID('12345678-1234-5678-9012-123456789012')
            uuid2 = uuid.UUID('87654321-4321-8765-2109-876543210987')
            mock_uuid.side_effect = [uuid1, uuid2]
            
            # Create two sandboxes
            id1 = manager.create_sandbox("ubuntu:latest")
            id2 = manager.create_sandbox("python:3.9")
            
            assert id1 == uuid1
            assert id2 == uuid2
            assert len(manager.sandboxes) == 2
            
            # Execute commands in both
            result1 = manager.execute_in_sandbox(id1, "ls")
            result2 = manager.execute_in_sandbox(id2, "python --version")
            
            assert result1["stdout"] == "output1"
            assert result2["stdout"] == "output2"
            
            # Stop all
            manager.stop_all()
            
            mock_sandbox1.stop.assert_called_once()
            mock_sandbox2.stop.assert_called_once()


@pytest.mark.parametrize("status", [
    SandboxStatus.CREATED,
    SandboxStatus.STARTING,
    SandboxStatus.STOPPED,
    SandboxStatus.ERROR
])
def test_execute_in_sandbox_non_running_statuses(status):
    """Test execute_in_sandbox with various non-running statuses"""
    with patch('docker.from_env'):
        manager = SandboxManager()
        test_uuid = uuid.uuid4()
        
        mock_sandbox = Mock()
        mock_sandbox.status = status
        manager.sandboxes[test_uuid] = mock_sandbox
        
        with pytest.raises(ValueError, match="not found or status not running"):
            manager.execute_in_sandbox(test_uuid, "test command")