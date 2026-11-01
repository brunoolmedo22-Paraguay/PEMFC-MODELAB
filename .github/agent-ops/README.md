# ModelLab agent operations

## Current status: MANUAL / NO LLM EXECUTION
GitHub Issues are the shared task queue. Creating an Issue does not launch Claude.
No Claude integration, credential, paid API, fallback, automatic retry, or autonomous merge is installed by this setup.

## Intended sequence
1. User and GPT define a bounded change.
2. GPT creates an Issue with acceptance criteria and test requirements.
3. User separately authorizes execution only after institutional permissions and billing controls are verified.
4. A future authorized runner reads the Issue and CLAUDE.md, creates a branch, edits code, runs tests, and opens a PR.
5. GPT and user review the PR; user approves merge to main.

## Billing safety gate
The Claude Team administrator must confirm permission for automated use and credential storage, subscription authentication compatibility, and that extra usage is disabled or otherwise technically prevented. Do not infer remaining quota from a GitHub event. No paid API fallback. Stop on usage-limit errors.

## Future multi-account policy
A second account is optional and requires separate authorization. No automatic cross-account fallback until explicit safeguards are verified. Do not pool or share credentials between institutional and personal accounts.

## Recovery
All work should be committed to feature branches early, with PRs and test logs, to survive agent interruption.
