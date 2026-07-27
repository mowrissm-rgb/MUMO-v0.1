# Deploying Specialist A (docking) to Cloud Run

Hugging Face now requires PRO for new Docker Spaces, so the specialists live on
Cloud Run instead. The dispatch client only needs a URL, so where a specialist
runs is not something the application knows or cares about.

## One-time setup (needs you — these are sign-ins to your own account)

1. Create a Google Cloud project at <https://console.cloud.google.com>
   and attach a billing account. Cloud Run's free tier is generous
   (2M requests/month) but Google still requires billing to be enabled.
2. Install the gcloud CLI: <https://cloud.google.com/sdk/docs/install>
3. Sign in and select the project:

   ```
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

4. Enable the APIs and create the image repository (once):

   ```
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   gcloud artifacts repositories create mumo --repository-format=docker --location=us-central1
   ```

## Deploy (repeatable, from the repo root)

```
gcloud builds submit --config deploy/space-a/cloudbuild.yaml .
```

Cloud Build builds the image and deploys it. No local Docker needed.

## Wire the front door to it

Cloud Run prints a service URL. Set it as a variable on the main MUMO Space:

```
MUMO_SPACE_DOCKING = https://mumo-docking-XXXX-uc.a.run.app
```

Until that variable is set, docking runs in-process exactly as it does today —
so deploying the specialist changes nothing until you point at it, and
unsetting the variable rolls back instantly with no redeploy.

## Check it

```
curl https://mumo-docking-XXXX-uc.a.run.app/health
```

Healthy looks like `{"ok": true, "specialist": "A", "vina": {"present": true, ...}}`.
`ok: false` means the image built but Vina is missing — the service reports
that honestly rather than accepting docking jobs it cannot run.
