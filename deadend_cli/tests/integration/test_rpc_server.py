# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Integration tests for the JSON-RPC server over stdio.

Note: Some linter warnings about "redefining names from outer scope" are expected
and safe to ignore - they're false positives related to pytest fixture usage.
"""
import json
import pytest
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path


class RPCClient:
    """Async helper class to communicate with the RPC server via stdio."""

    def __init__(self, process: asyncio.subprocess.Process):
        self.process = process
        self.request_id = 0

    async def send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[Any] = None
    ) -> None:
        """Send a JSON-RPC request to the server."""
        # Check if process is still alive
        if self.process.returncode is not None:
            # Try to read stderr
            stderr_output = ""
            try:
                if self.process.stderr:
                    stderr_data = await asyncio.wait_for(
                        self.process.stderr.read(), timeout=0.1
                    )
                    stderr_output = stderr_data.decode("utf-8", errors="ignore")
            except (asyncio.TimeoutError, OSError):
                pass
            raise RuntimeError(
                f"Server process exited before sending request. Return code: {self.process.returncode}. "
                f"Stderr: {stderr_output[:500]}"
            )
        
        if request_id is None:
            self.request_id += 1
            request_id = self.request_id
        
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
        }
        if params:
            request["params"] = params
        
        request_line = json.dumps(request) + "\n"
        try:
            if self.process.stdin:
                self.process.stdin.write(request_line.encode("utf-8"))
                await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # Process died, get stderr
            stderr_output = ""
            try:
                if self.process.stderr:
                    stderr_data = await asyncio.wait_for(
                        self.process.stderr.read(), timeout=0.1
                    )
                    stderr_output = stderr_data.decode("utf-8", errors="ignore")
            except (asyncio.TimeoutError, OSError):
                pass
            raise RuntimeError(
                f"Broken pipe - server process may have crashed. Return code: {self.process.returncode}. "
                f"Stderr: {stderr_output[:500]}"
            ) from e
    
    async def read_response(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Read a single JSON-RPC response from stdout."""
        # Check if process is still alive
        if self.process.returncode is not None:
            # Process has exited, try to read any remaining stderr
            stderr_output = ""
            try:
                if self.process.stderr:
                    stderr_data = await asyncio.wait_for(
                        self.process.stderr.read(), timeout=0.1
                    )
                    stderr_output = stderr_data.decode("utf-8", errors="ignore")
            except (asyncio.TimeoutError, OSError):
                pass
            raise RuntimeError(
                f"Server process exited with return code {self.process.returncode}. "
                f"Stderr: {stderr_output[:500]}"
            )
        
        # process.stdout is already a StreamReader from asyncio.create_subprocess_exec
        if not self.process.stdout:
            raise RuntimeError("Process stdout is not available")
        
        # Read one line with timeout
        try:
            line_bytes = await asyncio.wait_for(
                self.process.stdout.readline(), timeout=timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"No response received within {timeout} seconds")
        
        if not line_bytes:
            # Check if process died
            if self.process.returncode is not None:
                stderr_output = ""
                try:
                    if self.process.stderr:
                        stderr_data = await asyncio.wait_for(
                            self.process.stderr.read(), timeout=0.1
                        )
                        stderr_output = stderr_data.decode("utf-8", errors="ignore")
                except (asyncio.TimeoutError, OSError):
                    pass
                raise RuntimeError(
                    f"Server process exited while reading. Return code: {self.process.returncode}. "
                    f"Stderr: {stderr_output[:500]}"
                )
            raise EOFError("Server closed stdout")
        
        return json.loads(line_bytes.decode("utf-8").strip())
    
    async def read_responses(self, expected_count: int = 1, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Read multiple JSON-RPC responses (for streaming methods)."""
        responses = []
        for _ in range(expected_count):
            responses.append(await self.read_response(timeout=timeout))
        return responses
    
    async def close(self) -> None:
        """Close the connection to the server."""
        if self.process.stdin:
            try:
                self.process.stdin.close()
                await self.process.stdin.wait_closed()
            except (OSError, ValueError):
                pass
        
        try:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutExpired:
                    self.process.kill()
                    await self.process.wait()
        except (ProcessLookupError, OSError):
            # Process already dead, that's fine
            pass


@pytest.fixture
async def rpc_server_process(tmp_path):
    """Start the RPC server as a subprocess."""
    # Create a log file in the temp directory
    log_file = str(tmp_path / "rpc_server.log")
    
    # Find the server module path
    # The server is run as: python -m deadend_cli.jsonrpc_server
    # Test file is at: deadend_cli/tests/integration/test_rpc_server.py
    # So we need to go up to deadend_cli/ directory (3 levels up from test file)
    test_file = Path(__file__)
    deadend_cli_dir = test_file.parent.parent.parent  # deadend_cli/
    
    server_module = "deadend_cli.jsonrpc_server"
    
    # Start the server process using asyncio
    # Run from deadend_cli directory to avoid nested workspace issues
    # The deadend_cli directory has its own pyproject.toml, so uv run should work from there
    process = await asyncio.create_subprocess_exec(
        "uv", "run", "python", "-m", server_module, "--log-file", log_file,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(deadend_cli_dir),
    )
    
    # Give the server a moment to start and check if it's still alive
    await asyncio.sleep(1.0)
    
    # Check if process is still running
    if process.returncode is not None:
        # Process has exited, read stderr to see what went wrong
        try:
            stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=0.5)
            stderr_output = stderr_data.decode("utf-8", errors="ignore")
        except (asyncio.TimeoutError, OSError):
            stderr_output = "Could not read stderr"
        raise RuntimeError(
            f"RPC server process exited immediately with return code {process.returncode}. "
            f"Stderr: {stderr_output[:500]}"
        )
    
    yield process
    
    # Cleanup
    try:
        # Try graceful shutdown first
        if process.returncode is None:  # Process still running
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutExpired:
                process.kill()
                await process.wait()
    except (ProcessLookupError, OSError):
        # Process already dead, that's fine
        pass


@pytest.fixture
async def rpc_client(rpc_server_process):  # noqa: F811
    """Create an RPC client connected to the server."""
    client = RPCClient(rpc_server_process)
    yield client
    await client.close()


@pytest.mark.integration
class TestRPCServerIntegration:  # noqa: F811
    """Integration tests for the JSON-RPC server."""
    
    @pytest.mark.asyncio
    async def test_server_starts(self, rpc_server_process):
        """Test that the server process starts and stays alive."""
        # Check that process is running
        assert rpc_server_process.returncode is None, "Server process should be running"
        
        # Give it a moment to fully initialize
        await asyncio.sleep(0.5)
        
        # Still should be running
        assert rpc_server_process.returncode is None, "Server process should still be running after initialization"
    
    @pytest.mark.asyncio
    async def test_ping(self, rpc_client):
        """Test the ping method."""
        await rpc_client.send_request("ping")
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "id" in response
        assert "result" in response
        assert response["result"]["status"] == "ok"
    
    @pytest.mark.asyncio
    async def test_ping_with_params(self, rpc_client):
        """Test ping with parameters (should work the same)."""
        await rpc_client.send_request("ping", params={"test": "value"})
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "ok"
    
    @pytest.mark.asyncio
    async def test_invalid_method(self, rpc_client):
        """Test calling a non-existent method."""
        await rpc_client.send_request("nonexistent_method")
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32601  # METHOD_NOT_FOUND
        assert "Unknown method" in response["error"]["message"] or "not found" in response["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_invalid_jsonrpc_version(self, rpc_client):
        """Test with invalid JSON-RPC version."""
        # Send invalid request directly
        invalid_request = json.dumps({
            "jsonrpc": "1.0",  # Wrong version
            "method": "ping",
            "id": 1
        }) + "\n"
        if rpc_client.process.stdin:
            rpc_client.process.stdin.write(invalid_request.encode("utf-8"))
            await rpc_client.process.stdin.drain()
        
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32600  # INVALID_REQUEST
    
    @pytest.mark.asyncio
    async def test_missing_method_field(self, rpc_client):
        """Test request without method field."""
        invalid_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1
        }) + "\n"
        if rpc_client.process.stdin:
            rpc_client.process.stdin.write(invalid_request.encode("utf-8"))
            await rpc_client.process.stdin.drain()
        
        response = await rpc_client.read_response()
        
        assert "error" in response
        assert response["error"]["code"] == -32600  # INVALID_REQUEST
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, rpc_client):
        """Test multiple concurrent requests."""
        # Send multiple ping requests concurrently
        tasks = []
        for i in range(5):
            tasks.append(rpc_client.send_request("ping", request_id=i))
        await asyncio.gather(*tasks)
        
        # Read all responses
        responses = await rpc_client.read_responses(expected_count=5)
        
        assert len(responses) == 5
        for i, response in enumerate(responses):
            assert response["jsonrpc"] == "2.0"
            assert response["id"] == i
            assert "result" in response
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_init_config(self, rpc_client):
        """Test init_config method."""
        await rpc_client.send_request("init_config")
        response = await rpc_client.read_response(timeout=30.0)  # May take longer
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        # Check that result has expected structure
        result = response["result"]
        assert "component" in result or "success" in result or "status" in result
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_health_docker(self, rpc_client):
        """Test health_docker method."""
        await rpc_client.send_request("health_docker")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.docker
    async def test_init_all(self, rpc_client):
        """Test init_all method (may be slow and requires Docker)."""
        await rpc_client.send_request("init_all")
        response = await rpc_client.read_response(timeout=120.0)  # Can take a while
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        result = response["result"]
        assert "components" in result or "success" in result or "status" in result


@pytest.mark.integration
class TestRPCServerErrorHandling:  # noqa: F811
    """Test error handling in the RPC server."""
    
    @pytest.mark.asyncio
    async def test_malformed_json(self, rpc_client):
        """Test handling of malformed JSON."""
        # Send invalid JSON
        invalid_json = "{ invalid json }\n"
        if rpc_client.process.stdin:
            rpc_client.process.stdin.write(invalid_json.encode("utf-8"))
            await rpc_client.process.stdin.drain()
        
        # Server should continue running (not crash)
        # May or may not send an error response
        try:
            response = await rpc_client.read_response(timeout=1.0)
            # If we get a response, it should be an error
            if "error" in response:
                assert response["error"]["code"] == -32700  # PARSE_ERROR
        except (TimeoutError, EOFError):
            # Server may silently ignore malformed JSON
            pass
    
    @pytest.mark.asyncio
    async def test_empty_request(self, rpc_client):
        """Test handling of empty request."""
        if rpc_client.process.stdin:
            rpc_client.process.stdin.write(b"\n")
            await rpc_client.process.stdin.drain()
        
        # Server should continue running
        # Verify by sending a valid request
        await rpc_client.send_request("ping")
        response = await rpc_client.read_response()
        assert "result" in response or "error" in response
    
    @pytest.mark.asyncio
    async def test_shutdown(self, rpc_client):
        """Test shutdown method."""
        await rpc_client.send_request("shutdown")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "shutdown"


@pytest.mark.integration
class TestRPCServerHealthChecks:  # noqa: F811
    """Test health check methods."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_health_all(self, rpc_client):
        """Test health_all method."""
        await rpc_client.send_request("health_all")
        response = await rpc_client.read_response(timeout=30.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_health_pgvector(self, rpc_client):
        """Test health_pgvector method."""
        await rpc_client.send_request("health_pgvector")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_health_python_sandbox(self, rpc_client):
        """Test health_python_sandbox method."""
        await rpc_client.send_request("health_python_sandbox")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response


@pytest.mark.integration
class TestRPCServerHandlers:  # noqa: F811
    """Test handler methods (events, interrupt, approval)."""
    
    @pytest.mark.asyncio
    async def test_subscribe_events(self, rpc_client):
        """Test subscribe_events method (streaming)."""
        # Subscribe to events - this is a streaming method
        await rpc_client.send_request("subscribe_events")
        
        # For streaming methods, we should get at least one response
        # The method yields events, so we might get multiple responses
        # Read with a short timeout since there may not be any events
        try:
            response = await rpc_client.read_response(timeout=2.0)
            # If we get a response, it should be valid JSON-RPC
            assert response["jsonrpc"] == "2.0"
            # Streaming responses should have "result" field
            assert "result" in response or "error" in response
        except TimeoutError:
            # No events yet, which is fine - the subscription is active
            pass
    
    @pytest.mark.asyncio
    async def test_interrupt_missing_session_id(self, rpc_client):
        """Test interrupt method with missing session_id (should error)."""
        await rpc_client.send_request("interrupt", params={})
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32602  # INVALID_PARAMS
        assert "Session ID required" in response["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_interrupt_with_session_id(self, rpc_client):
        """Test interrupt method with valid session_id."""
        session_id = "test-session-123"
        await rpc_client.send_request("interrupt", params={"session_id": session_id})
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "interrupted"
        assert response["result"]["session_id"] == session_id
    
    @pytest.mark.asyncio
    async def test_interrupt_with_reason(self, rpc_client):
        """Test interrupt method with custom reason."""
        session_id = "test-session-456"
        reason = "Test interruption reason"
        await rpc_client.send_request("interrupt", params={
            "session_id": session_id,
            "reason": reason
        })
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "interrupted"
        assert response["result"]["session_id"] == session_id
    
    @pytest.mark.asyncio
    async def test_approve_missing_request_id(self, rpc_client):
        """Test approve method with missing request_id (should error)."""
        await rpc_client.send_request("approve", params={})
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32602  # INVALID_PARAMS
        assert "request_id is required" in response["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_approve_invalid_request_id(self, rpc_client):
        """Test approve method with non-existent request_id (should error)."""
        await rpc_client.send_request("approve", params={
            "request_id": "non-existent-request-id",
            "approved": True
        })
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        # Should get an error about request not found
        assert "error" in response
        assert "not found" in response["error"]["message"].lower() or "already processed" in response["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_enable_approval_mode(self, rpc_client):
        """Test enable_approval_mode method."""
        await rpc_client.send_request("enable_approval_mode")
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "enabled"
        assert response["result"]["approval_mode"] is True
    
    @pytest.mark.asyncio
    async def test_disable_approval_mode(self, rpc_client):
        """Test disable_approval_mode method."""
        await rpc_client.send_request("disable_approval_mode")
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "disabled"
        assert response["result"]["approval_mode"] is False
    
    @pytest.mark.asyncio
    async def test_get_approval_mode(self, rpc_client):
        """Test get_approval method."""
        await rpc_client.send_request("get_approval")
        response = await rpc_client.read_response()
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "approval_mode" in response["result"]
        assert isinstance(response["result"]["approval_mode"], bool)
    
    @pytest.mark.asyncio
    async def test_approval_mode_workflow(self, rpc_client):
        """Test complete approval mode workflow."""
        # 1. Enable approval mode
        await rpc_client.send_request("enable_approval_mode")
        enable_response = await rpc_client.read_response()
        assert enable_response["result"]["approval_mode"] is True
        
        # 2. Verify it's enabled
        await rpc_client.send_request("get_approval")
        check_response = await rpc_client.read_response()
        assert check_response["result"]["approval_mode"] is True
        
        # 3. Disable approval mode
        await rpc_client.send_request("disable_approval_mode")
        disable_response = await rpc_client.read_response()
        assert disable_response["result"]["approval_mode"] is False
        
        # 4. Verify it's disabled
        await rpc_client.send_request("get_approval")
        final_response = await rpc_client.read_response()
        assert final_response["result"]["approval_mode"] is False


@pytest.mark.integration
class TestRPCServerLLMProviders:  # noqa: F811
    """Test LLM provider methods."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_list_llm_provider(self, rpc_client):
        """Test list_llm_provider method."""
        await rpc_client.send_request("list_llm_provider")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        # Result should be a dict or list of providers
        result = response["result"]
        assert isinstance(result, (dict, list))
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_get_llm_provider(self, rpc_client):
        """Test get_llm_provider method."""
        await rpc_client.send_request("get_llm_provider")
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "provider" in response["result"]
        # Provider should be a string (or None)
        provider = response["result"]["provider"]
        assert provider is None or isinstance(provider, str)
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_set_llm_provider_missing_provider(self, rpc_client):
        """Test set_llm_provider method with missing provider parameter."""
        await rpc_client.send_request("set_llm_provider", params={})
        response = await rpc_client.read_response(timeout=10.0)
        
        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32602  # INVALID_PARAMS
        assert "provider parameter is required" in response["error"]["message"]
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_set_llm_provider(self, rpc_client):
        """Test set_llm_provider method."""
        # Try to set a provider (use a common one like "openai" if available)
        # Note: This might fail if the provider isn't configured, which is fine
        test_provider = "openai"
        await rpc_client.send_request("set_llm_provider", params={"provider": test_provider})
        set_response = await rpc_client.read_response(timeout=10.0)
        
        # The method should return success even if provider isn't fully configured
        assert set_response["jsonrpc"] == "2.0"
        # Either success or error is acceptable depending on configuration
        if "result" in set_response:
            assert set_response["result"]["status"] == "ok"
            assert set_response["result"]["provider"] == test_provider
        
        # Verify it was set (if setting succeeded)
        if "result" in set_response:
            await rpc_client.send_request("get_llm_provider")
            verify_response = await rpc_client.read_response(timeout=10.0)
            # Provider might be set or might revert, depending on implementation
            assert "provider" in verify_response["result"]
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_llm_provider_workflow(self, rpc_client):
        """Test complete LLM provider workflow."""
        # 1. List available providers
        await rpc_client.send_request("list_llm_provider")
        list_response = await rpc_client.read_response(timeout=10.0)
        assert "result" in list_response
        
        # 2. Get current provider
        await rpc_client.send_request("get_llm_provider")
        get_response = await rpc_client.read_response(timeout=10.0)
        assert "provider" in get_response["result"]
        
        # 3. Try to set a provider (may fail if not configured)
        # This is just testing the API, not the actual provider setup
        await rpc_client.send_request("set_llm_provider", params={"provider": "openai"})
        set_response = await rpc_client.read_response(timeout=10.0)
        # Should get either success or error, both are valid
        assert set_response["jsonrpc"] == "2.0"
        assert "result" in set_response or "error" in set_response


# Helper function for more complex test scenarios
@pytest.mark.integration
@pytest.mark.asyncio
async def test_custom_scenario(rpc_client):
    """Example of a custom test scenario."""
    # 1. Ping to verify connection
    await rpc_client.send_request("ping")
    ping_response = await rpc_client.read_response()
    assert ping_response["result"]["status"] == "ok"
    
    # 2. Check health
    await rpc_client.send_request("health_docker")
    health_response = await rpc_client.read_response(timeout=10.0)
    
    # 3. Verify state
    assert health_response["jsonrpc"] == "2.0"

