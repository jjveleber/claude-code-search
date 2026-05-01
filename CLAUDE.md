<!-- code-search:start -->
## Precision Protocol

**Rule:** Before using `Read`, `Grep`, or `Glob` — if the exact file path was not given to you in the current task, run `.venv-code-search/bin/python3 search_code.py "<query>"` first.

1. **File path given in task?**
   - **Yes** → go to step 2
   - **No** → run `.venv-code-search/bin/python3 search_code.py "<query>"`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use `search_code.py` when the file is already known — that is what `Grep` is for.**

**Search scope:** By default, `search_code.py` searches production and test code — documentation and generated files are excluded. Each result includes a `[prod]`, `[test]`, `[doc]`, or `[generated]` label.
- If results are all `[test]` files but you need implementation code, refine the query ("find the implementation of X") and note the mismatch to the user
- If the user's task is explicitly about tests, say so in the query ("find the test for X")
- Use `--all` to include documentation and generated files when explicitly needed

**Environment:** Always activate the virtual environment via `source .venv-code-search/bin/activate` before running project scripts.
<!-- code-search:end -->
