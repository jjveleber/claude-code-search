<!-- code-search:start -->
## Precision Protocol
1. **Search First:** Run `.venv/bin/python3 search_code.py "<query>"` to find relevant chunks.
2. **Verify:** Use the `Read` tool on the path from the search result.
3. **Validate:** If it's the wrong spot, refine the search query and repeat.
4. **Edit:** Only modify once the file content is verified.

**Environment:** Always activate the virtual environment via `source .venv/bin/activate` before running project scripts.
<!-- code-search:end -->

<!-- code-search-watch:start -->
## Session Startup
At the start of each session:
1. Run `.venv/bin/python3 index_project.py` to ensure the index is fresh
2. Run `.venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &` to start the watcher in the background
<!-- code-search-watch:end -->
