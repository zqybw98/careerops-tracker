# AGENTS.md

## Core Coding Principles

### 1. Think Before Coding
Before making changes:
- Restate the task in your own words.
- Identify assumptions and uncertainties.
- If the request is ambiguous, ask a clarification question before implementing.
- If there are multiple reasonable approaches, briefly compare them and choose the simplest one.

### 2. Simplicity First
Prefer the smallest correct solution.
- Do not add features that were not requested.
- Do not introduce abstractions for one-time use.
- Do not over-engineer APIs, configs, or helper layers.
- If a solution can be 50 lines instead of 200, prefer the 50-line version.

### 3. Surgical Changes
Only change what is necessary for the requested task.
- Do not refactor unrelated code.
- Do not reformat unrelated files.
- Do not delete or rewrite comments unless directly required.
- Match the existing project style, even if another style might be cleaner.
- Remove only unused code/imports created by your own change.

### 4. Goal-Driven Execution
Turn every task into a verifiable goal.
Before finishing:
- Explain what was changed.
- Run the smallest relevant test, lint, type check, or manual verification.
- If tests cannot be run, clearly say why.
- Review the diff for unintended changes.

## Done Means
A task is complete only when:
- The requested behavior is implemented.
- The change is minimal and localized.
- Relevant checks have passed or the reason for not running them is stated.
- No unrelated files or logic were modified.