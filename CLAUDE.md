# PEMFC ModelLab — Shared agent instructions

## Mission
Develop a scientifically defensible, reproducible PEMFC modeling application. Read the current README, CHANGELOG, source code, tests, and the specific GitHub Issue before changing anything. Source code is the authority for implemented equations and data contracts.

## Current scope
- Motor 1: device catalog, experimental curves, digitization, parameter identification/calibration, validation, and export.
- Motor 2: placeholder only until a separately approved specification is issued.
- Streamlit UI, including mobile/tablet usability.
- Never claim independent experimental validation from a fit or from data reused during parameter estimation.

## Engineering rules
1. Work on a dedicated branch and open a pull request. Never push feature changes directly to main or deploy without explicit approval.
2. Preserve the electrochemical model, numerical baselines, validated profiles, and existing experiments unless the approved task explicitly changes them.
3. Keep changes scoped to the Issue and include regression tests. Do not silently change scientific assumptions, units, or parameter bounds.
4. Never fabricate test results. Distinguish executed tests, blocked tests, and manual checks.
5. Document storage behavior, particularly browser-local persistence and portable ZIP exports.
6. No secrets in source code, logs, issues, pull requests, or artifacts.
7. Do not introduce paid APIs, external data transfers, or new cloud services without explicit approval.
8. On ambiguity, stop and ask rather than inventing requirements.

## Agent execution policy — SAFE BY DEFAULT
- Creating or editing Issues does NOT authorize agent execution.
- No Claude, Anthropic, or other LLM credentials are configured by these instructions.
- Any automated coding run requires a separate explicit human authorization and verified billing controls.
- Do not enable API billing, extra usage, fallback paid models, or automatic retries.
- If quota is exhausted, stop and report it. Do not switch accounts or payment methods automatically.
- A pull request is a proposal, not permission to merge.

## Handoff format
Each PR must state: Issue link; summary; modified files; tests actually executed; numerical baseline comparison when relevant; known limitations; deployment or dependency changes; any data migration implications.
