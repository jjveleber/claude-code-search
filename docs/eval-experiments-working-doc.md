# Eval Experiments Working Document

**Branch:** `feature/eval-framework`
**Worktree:** `.worktrees/eval-framework`
**Date:** 2026-03-26
**Status:** Plan complete — ready to execute

---

## Next Session Pickup

**Everything is ready to implement. Pick up here:**

1. Open Claude Code in the worktree:
   ```bash
   cd /path/to/claude-code-search/.worktrees/eval-framework
   ```

2. Tell Claude:
   > "Execute the implementation plan at `docs/superpowers/plans/2026-03-26-eval-experiment-runner.md`"

   Claude will invoke the `superpowers:executing-plans` or `superpowers:subagent-driven-development` skill and work through all 7 tasks.

**What will be built:**
- `eval/benchmarks/llvm.json` — updated with 18 prompts
- `eval/scripts/setup.sh` — one-time install + index
- `eval/scripts/validate.sh` — state checker
- `eval/scripts/reset.sh` — state transitions (baseline ↔ run)
- `eval/scripts/run-experiment.sh` — guided runner with clipboard copy (macOS)
- `eval/scripts/report.sh` — compare reports + create GitHub issue

**After implementation, the experiment workflow is:**
```bash
# One-time setup (if not done)
bash eval/scripts/setup.sh

# Run baseline (Claude without search)
bash eval/scripts/reset.sh baseline
bash eval/scripts/run-experiment.sh baseline   # walks 18 prompts, clipboard each

# Run treatment (Claude with search)
bash eval/scripts/reset.sh run
bash eval/scripts/run-experiment.sh run        # same 18 prompts

# Post results to GitHub
bash eval/scripts/report.sh \
  eval/results/<baseline>.json \
  eval/results/<run>.json
```

**Key files:**
- Plan: `docs/superpowers/plans/2026-03-26-eval-experiment-runner.md`
- Spec: `docs/superpowers/specs/2026-03-26-eval-experiment-runner-design.md`
- Benchmark prompts: below in this doc (also will be in `eval/benchmarks/llvm.json` after task 1)

---

---

## Goal

Establish a baseline (without claude-code-search) and a treatment run (with claude-code-search) against the llvm-project to measure the real-world impact of the tool on Claude's code navigation behavior.

**Test corpus:** `~/code-search-sandbox/llvm-project`
**Benchmark file:** `eval/benchmarks/llvm.json`

---

## Open Questions

- [x] Use all 18 prompts (2 per type) — **decided: all 18**
- [x] Replace the existing 3 prompts in `llvm.json` or fold them in? — **decided: replaced**

---

## Benchmark Prompts

18 prompts across 9 task types. `expected_files` will be empty until the baseline run is promoted via `eval.py promote`.

### 1. Navigation — find where X lives

**llvm-nav-001**
> Where is the `Value` class defined and what other classes inherit from it? I need to understand the base hierarchy of LLVM IR values.

- Key files: `llvm/include/llvm/IR/Value.h`, `llvm/lib/IR/Value.cpp`; subclasses: `Instruction`, `Function`, `BasicBlock`, `Constant`
- Why: foundational class scattered across many files; requires understanding inheritance hierarchy

**llvm-nav-002**
> I need to understand how the Global Value Numbering pass is implemented. Where does it live and what are the main methods?

- Key files: `llvm/include/llvm/Transforms/Scalar/GVN.h`, `llvm/lib/Transforms/Scalar/GVN.cpp`
- Why: major compiler pass with public interface + implementation details across multiple classes

---

### 2. Understanding — explain how X works across files

**llvm-understand-001**
> Explain how `LoopVectorizePass` uses results from other analyses like `DominatorTree`, `ScalarEvolution`, and `TargetTransformInfo` to drive vectorization decisions.

- Key files: `llvm/include/llvm/Transforms/Vectorize/LoopVectorize.h`, `llvm/lib/Transforms/Vectorize/LoopVectorize.cpp`
- Why: cross-file relationships between a pass and multiple analyses; data flow understanding required

**llvm-understand-002**
> I need to understand how `CodeGenFunction` manages code generation for a function, particularly how it coordinates with `IRBuilder`, debug info, and PGO instrumentation.

- Key files: `clang/lib/CodeGen/CodeGenFunction.cpp`, `CGDebugInfo.h`, `CodeGenPGO.h`
- Why: complex object composition across multiple systems; non-trivial cross-cutting concern

---

### 3. Modification — make a specific change

**llvm-modify-001**
> I want to extend the `ExpandMemCmp` pass to track which loads participate in size-dependent optimizations. What changes would I need to make to the `LoadEntry` structure and the code that uses it?

- Key files: `llvm/lib/CodeGen/ExpandMemCmp.cpp` — `LoadEntry` struct, `createLoadCmpBlocks()`, `setupResultBlockPHINodes()`, `emitLoadCompareBlock()`, `getCompareLoadPairs()`
- Why: data structure change with ripple effects across multiple methods; bounded but non-trivial

**llvm-modify-002**
> `SimplifyCFG` has several command-line flags like `HoistCommon` and `PHINodeFoldingThreshold`. I want to add a new option `--simplifycfg-aggressive-inlining` that affects how it folds basic blocks. What would need to be changed?

- Key files: `llvm/lib/Transforms/Utils/SimplifyCFG.cpp` — `cl::opt` definitions, `FoldBranchToCommonDest()`, `foldValueComparisonIntoPredecessors()`
- Why: touches infrastructure (CLI parsing) and implementation simultaneously

---

### 4. Debugging — trace why X behaves this way

**llvm-debug-001**
> I have code where GVN isn't eliminating what looks like a redundant load. GVN mentions `MemorySSA` and `MemoryDependenceAnalysis`. Why might it not eliminate the load? What conditions prevent it?

- Key files: `llvm/lib/Transforms/Scalar/GVN.cpp` — `processMemoryLoadPRE()`, `processNonLocalLoad()`, flags `GVNEnableMemorySSA`/`GVNEnableMemDep`
- Why: interaction between multiple analyses causing unexpected behavior; conditional logic tracing required

**llvm-debug-002**
> I notice `ExpandMemCmp` creates blocks for comparing 33 bytes as 2×16-byte loads and 1×1-byte load. How does it decide this decomposition? What determines `MaxLoadSize` and how does it compute `LoadSequence`?

- Key files: `llvm/lib/CodeGen/ExpandMemCmp.cpp` — `MaxLoadSize`, `NumLoadsPerBlockForZeroCmp`, `LoadSequence`, TTI queries
- Why: algorithmic decision-making logic; requires understanding both strategy and data structures

---

### 5. Dependency tracing — what calls X / what does X call

**llvm-deps-001**
> I need to understand the impact of modifying `SimplifyRecursivelyDeleted` in `SimplifyCFG`. What are all the call sites, and what does it depend on internally?

- Key files: `llvm/lib/Transforms/Utils/SimplifyCFG.cpp` — find definition + all call sites + callees like `replaceInstUsesWith()`, `eraseInstFromFunction()`
- Why: forward + backward dependency tracing; non-obvious call patterns

**llvm-deps-002**
> I want to understand the dependency analysis pipeline. Who calls `DependenceAnalysis::depends()` and what does it call internally?

- Key files: `llvm/lib/Analysis/DependenceAnalysis.cpp` — callers in loop/vectorization passes; internal helpers `strongSIVtest()`, `exactSIVtest()`, `gcdTest()`, `banerjeeTest()`
- Why: complex analysis with many internal helpers and diverse callers

---

### 6. Cross-cutting search — find all places where a pattern occurs

**llvm-xcut-001**
> I need to audit all places where `replaceAllUsesWith` is called across the LLVM codebase. Are there any pattern variations I should know about?

- Defined in: `llvm/lib/IR/Value.cpp`; called across Transforms, Analysis, CodeGen — very common pattern
- Variants: `replaceAllUsesWith()`, `replaceUsesOfWith()`, `replaceAllUsesPairwiseWith()`
- Why: common pattern across many files; requires finding variations and related functions

**llvm-xcut-002**
> Where are all the LLVM intrinsics defined (like `x86_sse2_*`), and what's the pattern for adding a new one? Show me how many different places use intrinsic IDs.

- Key files: `llvm/include/llvm/IR/Intrinsics*.td`, `IntrinsicsX86.h`, `X86InstCombineIntrinsic.cpp`
- Why: cross-cutting concern spanning TableGen, headers, and implementations; code generation pattern

---

### 7. API discovery — how do I accomplish X using this codebase

**llvm-api-001**
> I'm writing a pass that needs to insert a new instruction between two existing instructions in a basic block. What's the recommended API? Show me how it's done in existing passes.

- Solution: `IRBuilder<>`, `BasicBlock::iterator`, `Instruction::insertAfter()`
- Examples in: `llvm/lib/Transforms/Scalar/SimplifyCFG.cpp`, `GVN.cpp`, `EarlyCSE.cpp`
- Why: idiomatic API discovery through examples; important pattern used throughout

**llvm-api-002**
> I'm implementing a CFG transformation that merges basic blocks. How do I correctly update the dominance tree? Are there helpers to do this automatically?

- Solution: `DomTreeUpdater` class — `insertEdge()`, `deleteEdge()`, `applyUpdates()`
- Examples in: `llvm/lib/Transforms/Utils/SimplifyCFG.cpp`
- Why: non-obvious that a specialized helper exists; required for correctness

---

### 8. Comparison — what's the difference between X and Y

**llvm-compare-001**
> LLVM has both `DominatorTree` and `PostDominatorTree` analyses. What's the conceptual difference, and can you show me examples where each is used in different passes?

- Key files: `llvm/include/llvm/Analysis/Dominators.h`, `llvm/lib/Analysis/PostDominators.cpp`
- Usage: `DominatorTreeAnalysis` in SimplifyCFG/GVN vs `PostDominatorTreeAnalysis` in other contexts
- Why: subtle but important algorithmic differences; requires finding diverse usage examples

**llvm-compare-002**
> GVN supports both `MemorySSA` and `MemoryDependenceAnalysis`. What's the difference between them, and which does GVN prefer?

- Key files: `llvm/lib/Transforms/Scalar/GVN.cpp` — flags `GVNEnableMemorySSA`/`GVNEnableMemDep`, conditional logic
- Why: different approaches to the same problem; involves finding conditional logic and alternative implementations

---

### 9. Refactoring — if we change X, what else needs to change

**llvm-refactor-001**
> Suppose we want to change `IRBuilder::CreateLoad` to require an explicit alignment parameter (removing the default). What are all the places that would break, and how would we fix them systematically?

- Definition: `llvm/include/llvm/IR/IRBuilder.h`
- Call sites: SimplifyCFG.cpp, GVN.cpp, CodeGen files, analysis passes
- Why: broad-impact refactoring; requires finding all call site variations

**llvm-refactor-002**
> The `Value` class is the base of the LLVM IR hierarchy. If we add a new required field to its constructor, what would break? How many subclasses and initialization sites would need changes?

- Definition: `llvm/include/llvm/IR/Value.h`, `llvm/lib/IR/Value.cpp`
- Subclasses: `Instruction`, `Constant`, `Function`, `BasicBlock`, `GlobalValue` hierarchies
- Impact: cascades through CodeGen, IR creation, test files, clang AST code generation
- Why: fundamental infrastructure change; highly non-trivial scope; tests inheritance hierarchy understanding

---

## Next Steps

1. **Decide** on open questions above (18 vs 9 prompts; replace vs fold existing 3)
2. **Update** `eval/benchmarks/llvm.json` with finalized prompts
3. **Index** the llvm-project: `cd ~/code-search-sandbox/llvm-project && bash <path>/install.sh`
4. **Run baseline** (no search): `eval.py prepare baseline` → run each prompt in Claude Code → `eval.py analyze baseline`
5. **Promote** baseline to populate `expected_files`: `eval.py promote eval/results/<baseline>.json`
6. **Run treatment** (with search): `eval.py prepare run` → repeat prompts → `eval.py analyze run`
7. **Compare**: `eval.py compare eval/results/<baseline>.json eval/results/<run>.json`

---

## Existing Prompts (llvm.json as of 2026-03-26)

Three stubs with empty `expected_files` — to be replaced or merged:

- `llvm-001`: Find where SelectionDAG handles vector shuffle lowering *(overlaps with Navigation)*
- `llvm-002`: Find the inliner cost model and how it decides whether to inline *(overlaps with Understanding)*
- `llvm-003`: Find where register allocation spilling is handled *(overlaps with Navigation)*
