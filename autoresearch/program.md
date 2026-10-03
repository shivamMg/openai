# Azure OpenAI autoresearch

## Fixed setup

This project uses Azure OpenAI supervised fine-tuning for summarization. `prepare.py` is fixed: it creates the seeded CNN/DailyMail 3.0.0 pilot (1,000 train, 100 validation, 100 held-out eval), evaluates a base model, records metrics, and plots them. Do not edit it during a research session. The official test split remains untouched.

Create and install the local environment from `autoresearch/`:

- `python3 -m venv .venv`
- `.venv/bin/python -m pip install -r requirements.txt`

Ensure `.env` contains `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY`. For fine-tuning and deployment, also set `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, and `AZURE_OPENAI_RESOURCE_NAME`. Authenticate management-plane operations with `az login`. Never print or commit secrets.

Run preparation and the base-model baseline before any SFT job:

- `.venv/bin/python prepare.py`
- `.venv/bin/python prepare.py --eval-base`
- `.venv/bin/python prepare.py --plot`

Base evaluation calls the existing deployment name `gpt-4.1-nano`; it does not create, modify, or delete it. If that named deployment is absent, stop and ask the user to provision/identify the correct deployment. Base inference consumes tokens. Do not start SFT until a complete baseline is recorded for the current evaluation fingerprint.

## Experiment loop

1. Ask the user to confirm Azure fine-tuning and inference charges. Do not provision infrastructure or run unlimited experiments. Azure jobs take minutes to hours; there is no five-minute GPU budget.
2. Run the experiment directly on `main`; do not create a separate research branch. Before starting, verify that `main` is checked out and inspect the worktree for uncommitted changes. Do not overwrite, reset, or include unrelated user changes in experiment commits.
3. Run `.venv/bin/python train.py` once for the baseline SFT. Maximum three submitted jobs per session, failed submissions included. Resuming with `--job-id` does not spend another slot.
4. Only edit the experiment knobs at the top of `train.py` (`N_EPOCHS`, `LEARNING_RATE_MULTIPLIER`, `BATCH_SIZE`). Each candidate trains from the same base model and data; never modify the prompt, samples, decoding, scorer, or evaluation set.
5. Commit each hypothesis, run one experiment to completion, and compare its mean ROUGE-L F1 with the fixed base score and best prior SFT score. Higher is better. Keep a change only when it improves the score or gives a worthwhile simplification; otherwise revert only your own `train.py` edit. Git rollback does not undo Azure jobs or charges.
6. `result/results.tsv` is append-only metric history. Update only the existing run's `decision` and `description` fields (`keep`, `discard`, `crash`); never duplicate rows or alter measured values. Detailed aggregate metadata and per-example predictions are under `result/runs/<run_id>/`. Keep them across code rollbacks.
7. Regenerate `result/results.png` and `result/results.md` with `.venv/bin/python prepare.py --plot`. The outputs are local/offline. Stop at the three-job cap, on ambiguous job submission/status, or on unresolved deployment cleanup/auth errors. Never retry an ambiguous SFT submission automatically.

Fine-tuned deployments use the temporary Developer tier and are deleted after evaluation; retain the fine-tuned model ID in run metadata. Training and inference tokens still cost money. Developer tier has no SLA or data-residency guarantee. Never silently fall back to paid Standard hosting.
