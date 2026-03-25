<!-- code-search:start -->
## Precision Protocol

**Rule:** Before using `Read`, `Grep`, or `Glob` — if the exact file path was not given to you in the current task, run `.venv/bin/python3 search_code.py "<query>"` first.

1. **File path given in task?**
   - **Yes** → go to step 2
   - **No** → run `.venv/bin/python3 search_code.py "<query>"`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use `search_code.py` when the file is already known — that is what `Grep` is for.**

**Environment:** Always activate the virtual environment via `source .venv/bin/activate` before running project scripts.
<!-- code-search:end -->

