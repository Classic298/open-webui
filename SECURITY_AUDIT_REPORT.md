# Security Audit Report: Alleged Cryptominer Analysis

**Date:** 2024-05-22
**Target:** Open WebUI Repository
**Objective:** Investigate vulnerability report claiming XMRig cryptocurrency miner presence.

## Executive Summary

A comprehensive forensic analysis of the `open-webui` codebase was conducted to investigate reports of an XMRig cryptominer infection. **No evidence of the alleged cryptominer, malicious IOCs, or unauthorized background mining processes was found in the source code.**

The investigation identified features that allow for arbitrary code execution (Plugins/Functions, Code Interpreter), which are intended features but could be abused by an attacker to install a miner if the deployment is compromised or if malicious plugins are installed by a user.

The reported indicators of compromise (IOCs) likely stem from a compromised deployment environment, a malicious Docker image from an untrusted source, or post-deployment compromise, rather than malicious code within this repository.

## detailed Findings

### 1. Direct IOC Search
**Result:** NEGATIVE
**Scope:** Entire codebase.
**Search Terms:** "xmrig", "xmr", "monero", "cryptonight", "randomx", "pool.hashvault", "hashvault.pro", "85ReUbUj52QPQZH8rm8Bbz5pURoMYPQdfFQqWLp7Dn9Hie5fNtf9svsViKXdyF33LBKPPS4qsxEnbci6WnJbascM94SjDHy", "coinhive", "cryptoloot", "minero", "webminer".
**Findings:** None of the specified strings were found in the codebase.

### 2. Subprocess/Execution Analysis
**Result:** FALSE POSITIVE / INTENDED BEHAVIOR
**Scope:** `backend/`
**Findings:**

*   **File:** `backend/open_webui/utils/plugin.py`
    *   **Snippet:** `exec(content, module.__dict__)` and `subprocess.check_call(...)`
    *   **Risk:** HIGH (Intended Feature)
    *   **Explanation:** This file implements the Plugin/Function system. It allows users to define custom Python scripts (Functions) that are executed by the backend. It also supports installing dependencies via `pip`. This is a core feature for extensibility.
    *   **Relation to Miner:** If a malicious user (or attacker with access) added a Function containing code to download and run XMRig, this mechanism would execute it. However, the repository does not contain any such malicious Function by default.

*   **File:** `backend/open_webui/utils/code_interpreter.py`
    *   **Snippet:** `execute_code_jupyter`
    *   **Risk:** MEDIUM (Intended Feature)
    *   **Explanation:** This allows executing code in a Jupyter kernel. It relies on an external or local Jupyter service.
    *   **Relation to Miner:** Unlikely vector for the specific XMRig report unless the Jupyter environment itself was abused.

### 3. File System Operations
**Result:** NEGATIVE
**Scope:** Writes to `/tmp`.
**Findings:**
*   `backend/open_webui/utils/plugin.py` writes temporary files (`tempfile.NamedTemporaryFile`) to load modules. This is standard Python module loading behavior and does not match the reported `/tmp/*/xmrig-6.22.2` pattern.
*   No code was found that writes binaries or executables to `/tmp`.

### 4. Network/Download Analysis
**Result:** NEGATIVE
**Scope:** `requests`, `httpx`, `aiohttp` usages.
**Findings:**
*   `scripts/prepare-pyodide.js`: Downloads Python packages for the frontend-based Code Interpreter. Sources are standard (PyPI, jsdelivr).
*   `backend/open_webui/routers/retrieval.py`: Performs web searches and content scraping. Standard functionality.
*   No code was found that downloads from `hashvault.pro` or unknown IP addresses.

### 5. Startup/Trigger Analysis
**Result:** NEGATIVE
**Scope:** `main.py`, `lifespan`, middleware.
**Findings:**
*   `backend/open_webui/main.py`: Standard FastAPI startup.
*   `backend/open_webui/utils/plugin.py`: `install_tool_and_function_dependencies()` runs on startup. It installs dependencies for *active* functions in the database. In a fresh install, the database is clean, so no malicious dependencies are installed.

## Conclusion & Recommendations

The `open-webui` source code is **clean**. The report likely describes a compromised instance.

**Potential vectors for the reported infection:**
1.  **Malicious Plugin:** A user installed a "Tool" or "Function" that contained the miner payload.
2.  **Compromised Docker Image:** The user pulled a Docker image from a third-party registry that had the miner pre-installed.
3.  **Weak Credentials:** The instance was deployed with default credentials or exposed without authentication, allowing an attacker to log in and create a malicious Function or use the Code Interpreter to install the miner.

**Recommendation:**
*   Verify the integrity of the Docker image being used. Use only official images.
*   Audit installed "Functions" and "Tools" in the WebUI admin panel.
*   Ensure the instance is secured with strong authentication and not exposed publicly without protection.
