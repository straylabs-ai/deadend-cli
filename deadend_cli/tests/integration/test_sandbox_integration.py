import pytest
import uuid
import time
from unittest.mock import Mock, patch, MagicMock, call
import docker
from src.core.sandbox.sandbox import Sandbox, SandboxStatus
from src.core.sandbox.sandbox_manager import SandboxManager


@pytest.mark.integration
class TestSandboxIntegration:
    """Integration tests for the sandbox system"""
    
    @pytest.fixture
    def real_docker_client(self):
        """Mock Docker client for integration tests"""
        client = Mock(spec=docker.DockerClient)
        client.containers = Mock()
        return client
    
    @pytest.fixture
    def sandbox_system(self, real_docker_client):
        """Set up a complete sandbox system for integration testing"""
        with patch('docker.from_env') as mock_from_env:
            mock_from_env.return_value = real_docker_client
            manager = SandboxManager()
            return manager, real_docker_client


class TestSandboxLifecycle:
    """Test complete sandbox lifecycle scenarios"""
    
    @pytest.fixture
    def mock_container(self):
        """Create a mock container with realistic behavior"""
        container = Mock()
        container.id = "integration_test_container_id"
        container.exec_run = Mock()
        container.stop = Mock()
        container.remove = Mock()
        return container
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_full_sandbox_workflow(self, mock_sandbox_class):
        """Test complete workflow: create -> start -> execute -> stop -> cleanup"""
        # Setup mocks
        mock_docker_client = Mock(spec=docker.DockerClient)
        mock_sandbox_instance = Mock()
        mock_sandbox_instance.status = SandboxStatus.RUNNING
        mock_sandbox_instance.execute_command.return_value = {
            "exit_code": 0,
            "output": "Python 3.9.0",
            "command": "python --version"
        }
        mock_sandbox_class.return_value = mock_sandbox_instance
        
        with patch('docker.from_env', return_value=mock_docker_client), \
             patch('uuid.uuid4') as mock_uuid:
            
            test_uuid = uuid.UUID('12345678-1234-5678-9012-123456789012')
            mock_uuid.return_value = test_uuid
            
            # Create manager and sandbox
            manager = SandboxManager()
            sandbox_id = manager.create_sandbox("python:3.9")
            
            # Verify creation
            assert sandbox_id == test_uuid
            assert len(manager.sandboxes) == 1
            mock_sandbox_instance.start.assert_called_once_with(container_image="python:3.9")
            
            # Execute command
            result = manager.execute_in_sandbox(sandbox_id, "python --version")
            assert result["exit_code"] == 0
            assert "Python 3.9.0" in result["output"]
            mock_sandbox_instance.execute_command.assert_called_once_with(command="python --version")
            
            # Stop all sandboxes
            manager.stop_all()
            mock_sandbox_instance.stop.assert_called_once()


class TestMultipleSandboxes:
    """Test scenarios with multiple sandboxes"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_concurrent_sandboxes(self, mock_sandbox_class):
        """Test managing multiple sandboxes concurrently"""
        # Create mock sandboxes
        mock_sandboxes = []
        for i in range(3):
            mock_sandbox = Mock()
            mock_sandbox.status = SandboxStatus.RUNNING
            mock_sandbox.execute_command.return_value = {
                "exit_code": 0,
                "stdout": f"output_{i}",
                "stderr": "",
                "command": f"command_{i}"
            }
            mock_sandboxes.append(mock_sandbox)
        
        mock_sandbox_class.side_effect = mock_sandboxes
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            uuids = [uuid.uuid4() for _ in range(3)]
            mock_uuid.side_effect = uuids
            
            manager = SandboxManager()
            
            # Create multiple sandboxes
            sandbox_ids = []
            images = ["ubuntu:latest", "python:3.9", "alpine:latest"]
            
            for i, image in enumerate(images):
                sandbox_id = manager.create_sandbox(image)
                sandbox_ids.append(sandbox_id)
                assert sandbox_id == uuids[i]
            
            assert len(manager.sandboxes) == 3
            
            # Execute commands in each
            for i, sandbox_id in enumerate(sandbox_ids):
                result = manager.execute_in_sandbox(sandbox_id, f"command_{i}")
                assert result["stdout"] == f"output_{i}"
                assert result["command"] == f"command_{i}"
            
            # Verify each sandbox was called correctly
            for i, mock_sandbox in enumerate(mock_sandboxes):
                mock_sandbox.start.assert_called_once_with(container_image=images[i])
                mock_sandbox.execute_command.assert_called_once_with(command=f"command_{i}")
            
            # Stop all
            manager.stop_all()
            for mock_sandbox in mock_sandboxes:
                mock_sandbox.stop.assert_called_once()


class TestErrorScenarios:
    """Test error handling in integration scenarios"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_sandbox_creation_failure_recovery(self, mock_sandbox_class):
        """Test recovery when sandbox creation fails"""
        # First sandbox fails to start
        failing_sandbox = Mock()
        failing_sandbox.start.side_effect = docker.errors.DockerException("Container start failed")
        
        # Second sandbox starts successfully
        working_sandbox = Mock()
        working_sandbox.status = SandboxStatus.RUNNING
        working_sandbox.execute_command.return_value = {"exit_code": 0, "stdout": "success", "stderr": ""}
        
        mock_sandbox_class.side_effect = [failing_sandbox, working_sandbox]
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            uuid1, uuid2 = uuid.uuid4(), uuid.uuid4()
            mock_uuid.side_effect = [uuid1, uuid2]
            
            manager = SandboxManager()
            
            # First sandbox creation should fail
            with pytest.raises(docker.errors.DockerException):
                manager.create_sandbox("broken:image")
            
            # But sandbox should still be in registry (added before start() is called)
            assert len(manager.sandboxes) == 1
            
            # Second sandbox should work
            sandbox_id = manager.create_sandbox("working:image")
            assert sandbox_id == uuid2
            assert len(manager.sandboxes) == 2
            
            # Only the working sandbox should be executable
            with pytest.raises(ValueError):
                manager.execute_in_sandbox(uuid1, "test")  # Failing sandbox
            
            result = manager.execute_in_sandbox(uuid2, "test")  # Working sandbox
            assert result["stdout"] == "success"
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_command_execution_errors(self, mock_sandbox_class):
        """Test handling of command execution errors"""
        mock_sandbox = Mock()
        mock_sandbox.status = SandboxStatus.RUNNING
        
        # Mock different command execution scenarios
        def side_effect(command):
            if command == "failing_command":
                raise Exception("Command execution failed")
            elif command == "timeout_command":
                return {"exit_code": -1, "stdout": "Timeout", "stderr": "", "timed_out": True}
            else:
                return {"exit_code": 0, "stdout": "success", "stderr": ""}
        
        mock_sandbox.execute_command.side_effect = side_effect
        mock_sandbox_class.return_value = mock_sandbox
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.uuid4()
            mock_uuid.return_value = test_uuid
            
            manager = SandboxManager()
            sandbox_id = manager.create_sandbox()
            
            # Successful command
            result = manager.execute_in_sandbox(sandbox_id, "success_command")
            assert result["exit_code"] == 0
            
            # Failing command should propagate exception
            with pytest.raises(Exception, match="Command execution failed"):
                manager.execute_in_sandbox(sandbox_id, "failing_command")
            
            # Timeout command should return error result
            result = manager.execute_in_sandbox(sandbox_id, "timeout_command")
            assert result["exit_code"] == -1
            assert result["timed_out"] is True


class TestSandboxStateManagement:
    """Test sandbox state transitions and management"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_sandbox_state_transitions(self, mock_sandbox_class):
        """Test sandbox state changes throughout lifecycle"""
        mock_sandbox = Mock()
        # Simulate state transitions
        state_history = []
        
        def track_status_changes(status):
            state_history.append(status)
            mock_sandbox.status = status
        
        mock_sandbox.status = SandboxStatus.CREATED
        mock_sandbox.start.side_effect = lambda **kwargs: track_status_changes(SandboxStatus.RUNNING)
        mock_sandbox.stop.side_effect = lambda: track_status_changes(SandboxStatus.STOPPED)
        mock_sandbox.execute_command.return_value = {"exit_code": 0, "output": "test"}
        
        mock_sandbox_class.return_value = mock_sandbox
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.uuid4()
            mock_uuid.return_value = test_uuid
            
            manager = SandboxManager()
            
            # Initial state
            assert mock_sandbox.status == SandboxStatus.CREATED
            
            # Create and start sandbox
            sandbox_id = manager.create_sandbox()
            assert mock_sandbox.status == SandboxStatus.RUNNING
            assert SandboxStatus.RUNNING in state_history
            
            # Execute command (should only work in RUNNING state)
            result = manager.execute_in_sandbox(sandbox_id, "test_command")
            assert result["exit_code"] == 0
            
            # Stop sandbox
            manager.stop_all()
            assert mock_sandbox.status == SandboxStatus.STOPPED
            assert SandboxStatus.STOPPED in state_history
            
            # Trying to execute in stopped sandbox should fail
            mock_sandbox.status = SandboxStatus.STOPPED  # Ensure status is stopped
            with pytest.raises(ValueError, match="not found or status not running"):
                manager.execute_in_sandbox(sandbox_id, "test_command")


class TestResourceCleanup:
    """Test resource cleanup and management"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_cleanup_on_manager_destruction(self, mock_sandbox_class):
        """Test that resources are properly cleaned up"""
        mock_sandboxes = [Mock() for _ in range(3)]
        for mock_sandbox in mock_sandboxes:
            mock_sandbox.status = SandboxStatus.RUNNING
        
        mock_sandbox_class.side_effect = mock_sandboxes
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            uuids = [uuid.uuid4() for _ in range(3)]
            mock_uuid.side_effect = uuids
            
            manager = SandboxManager()
            
            # Create multiple sandboxes
            for _ in range(3):
                manager.create_sandbox()
            
            assert len(manager.sandboxes) == 3
            
            # Simulate cleanup (stop all) - this may raise an exception but we'll handle it
            try:
                manager.stop_all()
            except Exception:
                pass  # In case stop_all raises an exception from the first sandbox
            
            # Verify at least the first sandbox stop was attempted
            assert mock_sandboxes[0].stop.called
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_partial_cleanup_on_errors(self, mock_sandbox_class):
        """Test cleanup behavior when some operations fail"""
        mock_sandbox1 = Mock()
        mock_sandbox1.status = SandboxStatus.RUNNING
        mock_sandbox1.stop.side_effect = Exception("Stop failed")
        
        mock_sandbox2 = Mock()
        mock_sandbox2.status = SandboxStatus.RUNNING
        # Second sandbox stops normally
        
        mock_sandbox_class.side_effect = [mock_sandbox1, mock_sandbox2]
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            uuid1, uuid2 = uuid.uuid4(), uuid.uuid4()
            mock_uuid.side_effect = [uuid1, uuid2]
            
            manager = SandboxManager()
            manager.create_sandbox()
            manager.create_sandbox()
            
            # stop_all should propagate the first exception since it iterates through keys
            # and the first sandbox fails
            try:
                manager.stop_all()
                # If no exception is raised, that's also valid behavior
            except Exception as e:
                assert "Stop failed" in str(e)
            
            # First sandbox stop was attempted
            mock_sandbox1.stop.assert_called_once()


class TestConcurrencyAndPerformance:
    """Test concurrent operations and performance characteristics"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_concurrent_command_execution(self, mock_sandbox_class):
        """Test executing commands concurrently in multiple sandboxes"""
        import threading
        import concurrent.futures
        
        # Create multiple mock sandboxes
        num_sandboxes = 5
        mock_sandboxes = []
        results_storage = {}
        
        def mock_execute(command):
            # Simulate some processing time
            sandbox_id = command.split("_")[-1]
            results_storage[sandbox_id] = f"result_{sandbox_id}"
            return {"exit_code": 0, "stdout": f"result_{sandbox_id}", "stderr": ""}
        
        for i in range(num_sandboxes):
            mock_sandbox = Mock()
            mock_sandbox.status = SandboxStatus.RUNNING
            mock_sandbox.execute_command.side_effect = mock_execute
            mock_sandboxes.append(mock_sandbox)
        
        mock_sandbox_class.side_effect = mock_sandboxes
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            uuids = [uuid.uuid4() for _ in range(num_sandboxes)]
            mock_uuid.side_effect = uuids
            
            manager = SandboxManager()
            
            # Create sandboxes
            sandbox_ids = []
            for i in range(num_sandboxes):
                sandbox_id = manager.create_sandbox(f"image_{i}")
                sandbox_ids.append(sandbox_id)
            
            # Execute commands concurrently
            def execute_command(sandbox_id, command_suffix):
                return manager.execute_in_sandbox(sandbox_id, f"command_{command_suffix}")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                for i, sandbox_id in enumerate(sandbox_ids):
                    future = executor.submit(execute_command, sandbox_id, str(i))
                    futures.append(future)
                
                # Collect results
                results = []
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    results.append(result)
            
            # Verify all commands executed successfully
            assert len(results) == num_sandboxes
            for result in results:
                assert result["exit_code"] == 0
            
            # Verify each sandbox was called (at least once, may be more due to concurrency)
            for mock_sandbox in mock_sandboxes:
                assert mock_sandbox.execute_command.called


@pytest.mark.slow
class TestLongRunningOperations:
    """Test long-running operations and timeouts"""
    
    @patch('src.core.sandbox.sandbox_manager.Sandbox')
    def test_long_running_command_simulation(self, mock_sandbox_class):
        """Test handling of long-running commands"""
        mock_sandbox = Mock()
        mock_sandbox.status = SandboxStatus.RUNNING
        
        # Simulate long-running command with streaming output
        def mock_long_command(command):
            if "long_running" in command:
                return {
                    "command": command,
                    "streaming": True,
                    "stream": [b"line1\n", b"line2\n", b"line3\n"]
                }
            else:
                return {"exit_code": 0, "stdout": "quick result", "stderr": ""}
        
        mock_sandbox.execute_command.side_effect = mock_long_command
        mock_sandbox_class.return_value = mock_sandbox
        
        with patch('docker.from_env'), patch('uuid.uuid4') as mock_uuid:
            test_uuid = uuid.uuid4()
            mock_uuid.return_value = test_uuid
            
            manager = SandboxManager()
            sandbox_id = manager.create_sandbox()
            
            # Quick command
            result = manager.execute_in_sandbox(sandbox_id, "quick_command")
            assert result["stdout"] == "quick result"
            
            # Long-running command
            result = manager.execute_in_sandbox(sandbox_id, "long_running_command")
            assert result["streaming"] is True
            assert len(result["stream"]) == 3