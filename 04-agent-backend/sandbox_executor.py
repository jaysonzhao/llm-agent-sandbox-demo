import logging
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxInClusterConnectionConfig

logger = logging.getLogger(__name__)

WARMPOOL_NAME = "code-sandbox-pool"
NAMESPACE = "llm-sandbox-demo"
SANDBOX_TIMEOUT = 120


def create_client() -> SandboxClient:
    return SandboxClient(
        connection_config=SandboxInClusterConnectionConfig(use_pod_ip=False)
    )


def execute_code(client: SandboxClient, language: str, code: str) -> dict:
    sandbox = None
    try:
        sandbox = client.create_sandbox(
            warmpool=WARMPOOL_NAME,
            namespace=NAMESPACE,
            sandbox_ready_timeout=SANDBOX_TIMEOUT,
        )

        if language == "python":
            sandbox.files.write("/workspace/run.py", code)
            result = sandbox.commands.run(
                "cd /workspace && timeout 60 python run.py 2>&1"
            )
        elif language in ("bash", "sh", "shell"):
            sandbox.files.write("/workspace/run.sh", code)
            result = sandbox.commands.run(
                "cd /workspace && timeout 60 bash run.sh 2>&1"
            )
        elif language == "javascript":
            sandbox.files.write("/workspace/run.js", code)
            result = sandbox.commands.run(
                "cd /workspace && timeout 60 node run.js 2>&1"
            )
        else:
            sandbox.files.write("/workspace/run.py", code)
            result = sandbox.commands.run(
                "cd /workspace && timeout 60 python run.py 2>&1"
            )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "sandbox_name": sandbox._claim_name,
        }

    except Exception as e:
        logger.exception("Sandbox execution failed")
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "sandbox_name": sandbox._claim_name if sandbox else "N/A",
        }
    finally:
        if sandbox:
            try:
                sandbox.terminate()
            except Exception:
                logger.warning("Failed to terminate sandbox", exc_info=True)
