import pytest
import unittest
from unittest.mock import Mock, patch
from src.sandbox.sandbox import Sandbox


@pytest.fixture
def mock_client_docker():
    mock_client = Mock()

class TestSandbox(unittest.TestCase):

    @patch('docker.from_env')
    def test_sandbox_initialization(self, mock_docker_client):

        mock_client = Mock()
        mock_container = Mock()
        mock_container_id = "test_container_id"
        
        mock_docker_client.return_value = mock_client

        container_image = "ubuntu:latest"
        volume_path = "/tmp::/"
        start_process = "/bin/bash"

        def mock_run_command_generator():
            """Mocks ls return"""
            ls_return_ex = ["config.py  main.py  README.md  src  tests  uv.lock  zap_root_ca.cer"]
            for line in ls_return_ex: 
                yield line
        
        (exit_code, stream_mock) = (None, mock_run_command_generator())
        mock_container.exec_run.return_value = (exit_code, stream_mock)
        mock_client.containers.run.return_value = mock_container_id
        sandbox = Sandbox(mock_client, container_image, volume_path, start_process)

        assert sandbox.container == mock_container_id
         

def test_sandbox_init_creates_container(mock_docker_client, mock_container):
    mock_docker_client.containers.run.return_value = mock_container
    image = "ubuntu:latest"
    volume = "/tmp/test"
    command = "/bin/bash"
    sandbox = Sandbox(container_image=image, volume_path=volume, start_process=command)
    mock_docker_client.containers.run.assert_called_once_with(
        image=image,
        volumes=[volume],
        runtime='runsc',
        tty=True,
        command=command,
        detach=True
    )
    assert sandbox.image == image
    assert sandbox.volume == volume
    assert sandbox.command == command
    assert sandbox.container == mock_container

def test_run_command_yields_output(mock_docker_client, mock_container):
    mock_docker_client.containers.run.return_value = mock_container
    fake_output = [b'line1\n', b'line2\n']
    mock_container.exec_run.return_value = iter(fake_output)
    sandbox = Sandbox("img", "/tmp", "/bin/bash")
    result = list(sandbox.run_command("ls"))
    assert result == fake_output
    mock_container.exec_run.assert_called_once_with(cmd="ls", stream=True)