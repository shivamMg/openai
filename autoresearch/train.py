"""Submit one Azure OpenAI SFT experiment, deploy temporarily, and evaluate ROUGE-L."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import requests
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
from openai import OpenAI

import prepare

# Agent-editable experiment knobs. None delegates batch-size choice to Azure.
N_EPOCHS = 2
LEARNING_RATE_MULTIPLIER = 0.5
BATCH_SIZE = 1
TRAINING_TIER = "GlobalStandard"
POLL_SECONDS = 30
JOB_TIMEOUT_SECONDS = 6 * 60 * 60
ARM_API_VERSION = "2025-07-01-preview"


def azure_client():
    load_dotenv(prepare.ROOT / ".env")
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    return OpenAI(api_key=os.environ["AZURE_OPENAI_API_KEY"], base_url=endpoint + "/openai/v1/")


def management_config():
    keys = ["AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_OPENAI_RESOURCE_NAME"]
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        raise RuntimeError("Set Azure resource variables before SFT: " + ", ".join(missing))
    return (os.environ["AZURE_SUBSCRIPTION_ID"], os.environ["AZURE_RESOURCE_GROUP"], os.environ["AZURE_OPENAI_RESOURCE_NAME"])


def arm_request(method, url, **kwargs):
    token = AzureCliCredential().get_token("https://management.azure.com/.default").token
    headers = kwargs.pop("headers", {})
    headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Azure management API {method} failed ({response.status_code}): {response.text[:2000]}")
    return response


def resource_url(deployment):
    subscription, group, account = management_config()
    return (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account}/deployments/{deployment}")


def ensure_baseline():
    base = prepare.latest_base(prepare.evaluation_fingerprint())
    if base is None:
        raise RuntimeError("Base-model ROUGE-L baseline is required before SFT. Run: .venv/bin/python prepare.py --eval-base")
    return base


def budget_ledger():
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=prepare.ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        branch = "default"
    session_id = hashlib.sha1(branch.encode()).hexdigest()[:10]
    path = prepare.DATA / f"sft_submissions_{session_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"branch": branch, "jobs": []}


def persist_ledger(ledger):
    prepare.DATA.mkdir(parents=True, exist_ok=True)
    session_id = hashlib.sha1(ledger["branch"].encode()).hexdigest()[:10]
    (prepare.DATA / f"sft_submissions_{session_id}.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def poll_job(client, job_id):
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        job = client.fine_tuning.jobs.retrieve(job_id)
        print(f"job {job_id}: {job.status}", flush=True)
        if job.status in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(POLL_SECONDS)
    try:
        client.fine_tuning.jobs.cancel(job_id)
    finally:
        raise TimeoutError(f"Fine-tuning job exceeded {JOB_TIMEOUT_SECONDS // 3600} hours; cancellation requested")


def deploy(model_id, name):
    url = resource_url(name)
    arm_request("PUT", url, params={"api-version": ARM_API_VERSION}, json={
        "sku": {"name": "developertier", "capacity": 50},
        "properties": {"model": {"format": "OpenAI", "name": model_id, "version": "1"}},
    })
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        try:
            resource = arm_request("GET", url, params={"api-version": ARM_API_VERSION}).json()
        except RuntimeError as exc:
            if "(404)" in str(exc):
                time.sleep(15)
                continue
            raise
        state = resource.get("properties", {}).get("provisioningState", "")
        print(f"deployment {name}: {state}", flush=True)
        if state == "Succeeded":
            return
        if state in {"Failed", "Canceled", "Deleting", "Deleted"}:
            raise RuntimeError(f"Deployment provisioning ended in state {state}: {resource}")
        time.sleep(15)
    raise TimeoutError(f"Deployment {name} did not become ready within 30 minutes")


def delete_owned_deployment(name):
    try:
        response = arm_request("DELETE", resource_url(name), params={"api-version": ARM_API_VERSION})
    except RuntimeError as exc:
        if "(404)" in str(exc):
            return
        raise
    if response.status_code == 204:
        return
    url = resource_url(name)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        try:
            response = arm_request("GET", url, params={"api-version": ARM_API_VERSION})
        except RuntimeError as exc:
            if "(404)" in str(exc):
                return
            raise
        if response.json().get("properties", {}).get("provisioningState") == "Deleting":
            time.sleep(10)
        else:
            return


def run(job_id=None):
    load_dotenv(prepare.ROOT / ".env")
    for path in (prepare.TRAIN_FILE, prepare.VALID_FILE, prepare.EVAL_FILE):
        if not path.exists():
            raise RuntimeError("Run prepare.py and prepare.py --eval-base before training")
    baseline = ensure_baseline()
    management_config()
    # Fail management-plane authentication before uploading data or submitting a billable job.
    AzureCliCredential().get_token("https://management.azure.com/.default")
    client = azure_client()
    ledger = budget_ledger()
    if job_id is None:
        if len(ledger["jobs"]) >= 3:
            raise RuntimeError("This autoresearch session has reached its three-submission SFT cap")
        if any(not job.get("job_id") for job in ledger["jobs"]):
            raise RuntimeError("A prior job submission has an unknown outcome; reconcile it in Azure before proceeding")
        with prepare.TRAIN_FILE.open("rb") as stream:
            training_file = client.files.create(file=stream, purpose="fine-tune")
        with prepare.VALID_FILE.open("rb") as stream:
            validation_file = client.files.create(file=stream, purpose="fine-tune")
        for file_id in (training_file.id, validation_file.id):
            deadline = time.monotonic() + 1800
            while True:
                info = client.files.retrieve(file_id)
                if info.status == "processed":
                    break
                if info.status in {"error", "deleted"}:
                    raise RuntimeError(f"Fine-tuning file {file_id} status: {info.status}")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Fine-tuning file {file_id} processing timed out")
                time.sleep(5)
        hyperparameters = {"n_epochs": N_EPOCHS, "learning_rate_multiplier": LEARNING_RATE_MULTIPLIER}
        if BATCH_SIZE is not None:
            hyperparameters["batch_size"] = BATCH_SIZE
        # Reserve a slot before the network call: a lost response must never trigger a duplicate billable job.
        job_record = {
            "job_id": None, "created_at": datetime.now(timezone.utc).isoformat(),
            "training_file_id": training_file.id, "validation_file_id": validation_file.id,
            "status": "submission_pending", "hyperparameters": hyperparameters,
        }
        ledger["jobs"].append(job_record)
        persist_ledger(ledger)
        response = client.fine_tuning.jobs.create(
            model=prepare.FT_MODEL, training_file=training_file.id, validation_file=validation_file.id,
            suffix=f"auto-{uuid.uuid4().hex[:8]}", seed=prepare.SEED,
            method={"type": "supervised", "supervised": {"hyperparameters": hyperparameters}},
            extra_body={"trainingType": TRAINING_TIER},
        )
        job_id = response.id
        job_record["job_id"] = job_id
        job_record["status"] = "submitted"
        persist_ledger(ledger)
    else:
        if job_id not in {job["job_id"] for job in ledger["jobs"]}:
            raise RuntimeError("Resume refused: job ID is not in this local session's submission ledger")

    job_record = next(entry for entry in ledger["jobs"] if entry["job_id"] == job_id)
    job = poll_job(client, job_id)
    job_record["status"] = job.status
    job_record["fine_tuned_model"] = job.fine_tuned_model
    persist_ledger(ledger)
    if job.status != "succeeded":
        raise RuntimeError(f"Fine-tuning job {job_id} ended with status {job.status}")
    model_id = job.fine_tuned_model
    if not model_id:
        raise RuntimeError(f"Successful job {job_id} did not return a fine_tuned_model ID")
    deployment_name = re.sub(r"[^a-zA-Z0-9-]", "-", f"ar-{job_id}")[:60].lower()
    job_record["deployment_name"] = deployment_name
    persist_ledger(ledger)
    try:
        deploy(model_id, deployment_name)
        # Azure may report provisioned slightly before the inference endpoint is ready.
        time.sleep(20)
        return prepare.score_deployment(
            deployment_name, "sft", job_id=job_id, model_id=model_id, epochs=N_EPOCHS,
            lr=LEARNING_RATE_MULTIPLIER, batch_size=BATCH_SIZE if BATCH_SIZE is not None else "auto",
            description=f"SFT; baseline {baseline['run_id']}",
            experiment_seconds=(datetime.now(timezone.utc) - datetime.fromisoformat(job_record["created_at"])).total_seconds(),
        )
    finally:
        delete_owned_deployment(deployment_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", help="Resume an already-submitted job; does not consume another job slot")
    args = parser.parse_args()
    try:
        run(args.job_id)
    except KeyboardInterrupt:
        print("Interrupted. Check the Azure job before starting another experiment.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
