"""
test_sandbox.py
E2E tests for LlmSandboxToolSpec.
Requires Docker Desktop to be running.
conftest.py autoskip handles Docker-unavailable case.
"""
import pytest

from services.sandbox import LlmSandboxToolSpec, RemoteFile


@pytest.fixture
def sandbox(tmp_path):
    sb = LlmSandboxToolSpec(local_save_path=str(tmp_path))
    yield sb
    sb.close()


@pytest.mark.docker
class TestLlmSandboxInit:
    def test_init_creates_pool(self, sandbox):
        assert hasattr(sandbox, "_pool")

    def test_local_save_path_stored(self, sandbox, tmp_path):
        assert sandbox._local_save_path == str(tmp_path)


@pytest.mark.docker
class TestLlmSandboxCodeExecution:
    def test_run_code_executes_python(self, sandbox):
        result = sandbox.run_code('print("hello from sandbox")')
        assert "hello from sandbox" in result

    def test_run_code_error_format(self, sandbox):
        result = sandbox.run_code("raise RuntimeError('intentional error')")
        assert "ERROR" in result

    def test_run_code_can_import_pptx(self, sandbox):
        result = sandbox.run_code("import pptx; print('pptx version:', pptx.__version__)")
        assert "pptx version:" in result


@pytest.mark.docker
class TestLlmSandboxFileOps:
    def test_upload_file_message(self, sandbox, tmp_path):
        local_file = tmp_path / "test_upload.txt"
        local_file.write_text("hello")
        result = sandbox.upload_file(str(local_file))
        assert "Uploaded" in result

    def test_list_files_returns_remote_files(self, sandbox, tmp_path):
        local_file = tmp_path / "test_list.txt"
        local_file.write_text("hello")
        sandbox.upload_file(str(local_file))
        files = sandbox.list_files()
        assert all(isinstance(f, RemoteFile) for f in files)

    def test_list_files_str_contains_path(self, sandbox, tmp_path):
        local_file = tmp_path / "test_str.txt"
        local_file.write_text("hello")
        sandbox.upload_file(str(local_file))
        result = sandbox.list_files_str()
        assert "/sandbox/" in result

    def test_download_file_to_local(self, sandbox, tmp_path):
        # Upload a file then download it back
        local_file = tmp_path / "upload.txt"
        local_file.write_text("round-trip content")
        sandbox.upload_file(str(local_file))

        downloaded = tmp_path / "downloaded.txt"
        sandbox.download_file_to_local("/sandbox/upload.txt", str(downloaded))
        assert downloaded.exists()
        assert "round-trip content" in downloaded.read_text()


@pytest.mark.docker
class TestLlmSandboxToolList:
    def test_to_tool_list_length(self, sandbox):
        tools = sandbox.to_tool_list()
        assert len(tools) == 3

    def test_tool_names(self, sandbox):
        tools = sandbox.to_tool_list()
        names = {t.metadata.name for t in tools}
        assert names == {"run_code", "list_files", "upload_file"}
