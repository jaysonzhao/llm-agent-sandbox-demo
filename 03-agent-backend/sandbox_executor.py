import logging
import re

import k8s_agent_sandbox.constants as _consts
import k8s_agent_sandbox.k8s_helper as _kh
_consts.CLAIM_API_VERSION = "v1beta1"
_consts.SANDBOX_API_VERSION = "v1beta1"
_kh.CLAIM_API_VERSION = "v1beta1"
_kh.SANDBOX_API_VERSION = "v1beta1"

from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxDirectConnectionConfig

logger = logging.getLogger(__name__)

WARMPOOL_NAME = "code-sandbox-pool"
TEMPLATE_NAME = "code-execution-template"
NAMESPACE = "llm-sandbox-demo"
SANDBOX_TIMEOUT = 120
ROUTER_URL = "http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080"

PREINSTALLED = {
    "os", "sys", "json", "math", "re", "datetime", "time", "collections",
    "itertools", "functools", "pathlib", "io", "csv", "random", "string",
    "hashlib", "base64", "subprocess", "shutil", "glob", "tempfile",
    "typing", "dataclasses", "enum", "copy", "textwrap", "argparse",
    "unittest", "pprint", "logging", "traceback", "contextlib",
    "numpy", "np", "pandas", "pd", "scipy", "sympy", "matplotlib",
    "requests", "plt",
}

IMPORT_RE = re.compile(
    r'^\s*(?:import|from)\s+([\w]+)', re.MULTILINE
)


def _extract_pip_packages(code: str) -> list:
    modules = set(IMPORT_RE.findall(code))
    to_install = modules - PREINSTALLED
    pkg_map = {"sklearn": "scikit-learn", "cv2": "opencv-python", "PIL": "Pillow",
               "bs4": "beautifulsoup4", "yaml": "pyyaml", "dotenv": "python-dotenv"}
    return [pkg_map.get(m, m) for m in to_install]


def create_client() -> SandboxClient:
    return SandboxClient(
        connection_config=SandboxDirectConnectionConfig(api_url=ROUTER_URL)
    )


def execute_code(client: SandboxClient, language: str, code: str) -> dict:
    sandbox = None
    try:
        sandbox = client.create_sandbox(
            warmpool=WARMPOOL_NAME,
            namespace=NAMESPACE,
            sandbox_ready_timeout=SANDBOX_TIMEOUT,
        )

        if language == "python" or language not in ("bash", "sh", "shell", "javascript"):
            pkgs = _extract_pip_packages(code)
            if pkgs:
                logger.info("Installing packages: %s", pkgs)
                sandbox.commands.run(f"pip install --quiet {' '.join(pkgs)}")
            sandbox.files.write("run.py", code)
            result = sandbox.commands.run("timeout 60 python run.py")
        elif language in ("bash", "sh", "shell"):
            sandbox.files.write("run.sh", code)
            result = sandbox.commands.run("timeout 60 bash run.sh")
        elif language == "javascript":
            sandbox.files.write("run.js", code)
            result = sandbox.commands.run("timeout 60 node run.js")

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "sandbox_name": sandbox.claim_name,
        }

    except Exception as e:
        logger.exception("Sandbox execution failed")
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "sandbox_name": sandbox.claim_name if sandbox else "N/A",
        }
    finally:
        if sandbox:
            try:
                sandbox.terminate()
            except Exception:
                logger.warning("Failed to terminate sandbox", exc_info=True)
