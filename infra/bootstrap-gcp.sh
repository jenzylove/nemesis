#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-us-central1}"
RUNTIME_ACCOUNT="nemesis-runtime@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "${GOOGLE_CLOUD_PROJECT}" --format='value(projectNumber)')"
BUILD_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud config set project "${GOOGLE_CLOUD_PROJECT}"
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  pubsub.googleapis.com \
  cloudscheduler.googleapis.com

gcloud artifacts repositories describe nemesis --location "${REGION}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create nemesis --repository-format docker --location "${REGION}"

gcloud iam service-accounts describe "${RUNTIME_ACCOUNT}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create nemesis-runtime --display-name "NEMESIS Cloud Run runtime"

for role in roles/datastore.user roles/aiplatform.user roles/secretmanager.secretAccessor roles/pubsub.publisher roles/run.invoker; do
  gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
    --member "serviceAccount:${RUNTIME_ACCOUNT}" --role "${role}" >/dev/null
done

gcloud pubsub topics describe nemesis-case-events >/dev/null 2>&1 || gcloud pubsub topics create nemesis-case-events

gcloud pubsub subscriptions describe nemesis-case-events-push >/dev/null 2>&1 || gcloud pubsub subscriptions create nemesis-case-events-push \
  --topic nemesis-case-events \
  --push-endpoint "https://nemesis-api-staging-h7bnd6kzfq-uc.a.run.app/internal/events/pubsub" \
  --push-auth-service-account "${RUNTIME_ACCOUNT}" \
  --push-auth-token-audience "https://nemesis-api-staging-h7bnd6kzfq-uc.a.run.app"

gcloud scheduler jobs describe nemesis-monitor-tick --location "${REGION}" >/dev/null 2>&1 || gcloud scheduler jobs create http nemesis-monitor-tick \
  --location "${REGION}" --schedule "*/5 * * * *" --uri "https://nemesis-api-staging-h7bnd6kzfq-uc.a.run.app/internal/monitoring/tick" \
  --http-method POST --oidc-service-account-email "${RUNTIME_ACCOUNT}" \
  --oidc-token-audience "https://nemesis-api-staging-h7bnd6kzfq-uc.a.run.app"

for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
    --member "serviceAccount:${BUILD_ACCOUNT}" --role "${role}" >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_ACCOUNT}" \
  --member "serviceAccount:${BUILD_ACCOUNT}" --role roles/iam.serviceAccountUser >/dev/null

gcloud firestore databases describe --database='(default)' >/dev/null 2>&1 || \
  gcloud firestore databases create --database='(default)' --location="${FIRESTORE_LOCATION}" --type=firestore-native

for secret in nemesis-staging-ethereum-rpc nemesis-staging-base-rpc nemesis-staging-bitquery-token; do
  gcloud secrets describe "${secret}" >/dev/null 2>&1 || \
    gcloud secrets create "${secret}" --replication-policy automatic
done

echo "Infrastructure ready. Add one version to each staging RPC secret and nemesis-staging-bitquery-token, then submit cloudbuild.yaml."
