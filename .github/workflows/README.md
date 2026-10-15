# Centralized GitHub Actions Workflows

This document describes the reusable GitHub Actions workflows used to build frontend applications, build and publish Docker images, update GitOps deployment manifests for Argo CD, and send pipeline status notifications to Discord.

All the workflows use `workflow_call`, which means they are designed to be called by another workflow rather than triggered directly by a `push` or `pull_request` event. A calling workflow supplies the required inputs and secrets.

## Table of contents

1. [Architecture at a glance](#architecture-at-a-glance)
2. [Workflow 1: Build a Node.js project and upload to S3](#workflow-1-build-a-nodejs-project-and-upload-to-s3)
3. [Workflow 2: Update the image SHA for Argo CD](#workflow-2-update-the-image-sha-for-argocd)
4. [Workflow 3: Build a Docker image and push to Harbor](#workflow-3-build-a-docker-image-and-push-to-harbor)
5. [Workflow 4: Send a Discord notification](#workflow-4-send-a-discord-notification)
6. [How the workflows fit together](#how-the-workflows-fit-together)
7. [Security and permissions](#security-and-permissions)
8. [Operational considerations and limitations](#operational-considerations-and-limitations)
9. [Example caller workflow](#example-caller-workflow)
10. [Troubleshooting](#troubleshooting)

---

## Architecture at a glance

The workflows support two deployment patterns.

### Static frontend deployment

```text
Calling workflow
    |
    v
Checkout source and submodules
    |
    v
Set up Node.js and install dependencies
    |
    v
Build frontend assets
    |
    v
Assume AWS role using GitHub OIDC
    |
    v
Sync ./dist to an S3 bucket
```

### Containerized application deployment with GitOps

```text
Calling workflow
    |
    v
Build Docker image using the project's Dockerfile
    |
    v
Push image to Harbor tagged with the Git commit SHA
    |
    v
Update the image tag in the GitOps repository
    |
    v
Argo CD detects the GitOps change and reconciles the application
```

The Discord notification workflow can be called by either pattern to report the result of the jobs in the calling workflow.

> These workflows are reusable building blocks. The calling workflow defines the trigger, job dependencies, environment selection, and which reusable workflows run.

---

## Workflow 1: Build a Node.js project and upload to S3

**Workflow name:** `CD - Build Node Project & Upload to S3`

**Purpose:** Install dependencies, build a Node.js-based frontend or other static-site project, and upload the generated files to Amazon S3.

### Inputs

| Input | Required | Purpose |
|---|---:|---|
| `runs-on` | Yes | Runner label for the job, such as `ubuntu-latest`. The job expression falls back to `ubuntu-latest` if the input is empty. |
| `project-name` | Yes | Project identifier used in the S3 destination path. |
| `node-version` | Yes | Node.js version to install. The step expression falls back to `20` if the input is empty. |
| `aws-role` | Yes | AWS IAM role ARN to assume for deployment. |
| `bucket-name` | Yes | Name of the destination S3 bucket. |

### Secret

| Secret | Required | Purpose |
|---|---:|---|
| `ALL_REPOS_READONLY` | Yes | Token used by checkout to access the repository and any private submodules. |

### Permissions

```yaml
permissions:
  id-token: write
```

This grants the workflow permission to request a GitHub OIDC identity token. The AWS credentials action can use that token to assume the supplied IAM role. No other `GITHUB_TOKEN` permissions are explicitly granted by this workflow-level permissions block.

### Execution steps

1. **Checkout repository**
   - Uses `actions/checkout@v4`.
   - Recursively checks out submodules, including the referenced Vue shared submodule.
   - Sets `fetch-depth: 0` to fetch full history.
   - Uses `ALL_REPOS_READONLY` as the checkout token.

2. **Set up Node.js**
   - Uses `actions/setup-node@v4`.
   - Installs the requested Node.js version.
   - Enables npm caching.
   - Uses all `package-lock.json` files as cache dependency paths.

3. **Fix executable permissions**
   - Runs `find` to make files under `node_modules/.bin/` executable.
   - This can help when executable permissions are missing in the runner workspace or dependency tree.

4. **Install dependencies**
   - Runs `npm run install:all`.
   - This is a custom npm script and must exist in the repository's `package.json`.
   - The commented-out `working-directory` means the command runs from the checked-out repository root.

5. **Build the project**
   - Runs `npm run build`.
   - The actual build behavior depends on the repository's `package.json` scripts.
   - The workflow assumes the build output is available at `./dist`.

6. **Configure AWS credentials**
   - Uses `aws-actions/configure-aws-credentials@v4`.
   - Uses AWS region `eu-central-1`.
   - Assumes the role supplied by `aws-role`.
   - Uses `UploadSpaToS3` as the role session name.

7. **Deploy to S3**
   - Sets `DEPLOY_ENV` to `github.ref_name`.
   - Synchronizes `./dist` to:
     `s3://<bucket-name>/<project-name>/<branch-or-ref-name>`
   - Uses `--delete`, which removes destination objects that are not present in the local `dist` directory.

### S3 destination example

If the bucket is `frontend-artifacts`, the project is `tracker-spa`, and the workflow runs on a branch named `staging`, the destination is:

```text
s3://frontend-artifacts/tracker-spa/staging
```

The environment folder is derived from the Git ref name; it is not independently validated or mapped to an environment by this workflow.

### Suitable projects

This workflow is suited to Node.js-based frontend or static-site projects whose build produces files that can be hosted from S3. React, Vue, and Angular projects may be suitable when their install/build commands and output directory match the workflow's assumptions.

It is **not a language-agnostic deployment workflow**. A Python, Java, or .NET backend would usually require a different build and deployment process.

### Important assumptions

- `npm run install:all` exists and installs the required dependencies.
- `npm run build` produces `./dist`.
- The checked-out repository root is the correct build directory.
- The assumed AWS role has the required S3 permissions.
- The destination bucket and path are correct, because `--delete` can remove files from the destination.

---

## Workflow 2: Update the image SHA for Argo CD

**Workflow name:** `CD - Update Image SHA for ArgoCD`

**Purpose:** Update a container image tag in the `Star-Communications/git-ops` repository so the GitOps configuration points to the image built for the current Git commit.

This workflow does not build or push the image. It changes the GitOps configuration that identifies which image should be deployed.

### Inputs

| Input | Required | Purpose |
|---|---:|---|
| `runs-on` | Yes | Runner label, such as `ubuntu-latest`; the job expression falls back to `ubuntu-latest` if empty. |
| `gitOps-project-name` | Yes | Project directory name under `k8s/manifests/starcom-projects/`. |
| `values-file-env` | No | Environment suffix used to find Helm values files. Defaults to an empty string. |

### Secret

| Secret | Required | Purpose |
|---|---:|---|
| `ARGOCD_REPO_TOKEN` | Yes | Token with write access to the GitOps repository. |

### Permissions

```yaml
permissions:
  id-token: write
```

The shown steps use a GitHub secret token to check out and push to the GitOps repository. The OIDC permission is present, but this workflow does not itself configure cloud credentials or use an OIDC token in the shown steps.

### Execution steps

1. **Set environment variables**
   - `ENV_NAME` is populated from `values-file-env`.
   - `GITHUB_SHA` is populated from the triggering commit SHA.
   - The comment states that the calling workflow is responsible for any environment fallback.

2. **Checkout the GitOps repository**
   - Checks out `Star-Communications/git-ops`.
   - Uses `ARGOCD_REPO_TOKEN`.
   - Checks out the `main` branch.

3. **Update Helm values**
   - Searches for files matching:
     `k8s/manifests/starcom-projects/<gitOps-project-name>/values-<ENV_NAME>*.yaml`
   - Replaces lines matching `tag:.*` with the current commit SHA.
   - Enables Bash `nullglob` so a pattern with no matching files expands to an empty list instead of remaining as a literal pattern.

4. **Commit and push**
   - Configures the Git author as `github-actions[bot]`.
   - Stages changes.
   - Checks whether the working tree has changes.
   - If changes exist, commits and pushes them to `main`.
   - If no changes exist, prints a message and exits without creating an empty commit.

### Example

For these inputs:

```yaml
gitOps-project-name: tracker-api
values-file-env: staging
```

The workflow looks for matching files under:

```text
k8s/manifests/starcom-projects/tracker-api/values-staging*.yaml
```

It updates the image tag to the triggering commit SHA, for example:

```yaml
tag: "2ef299632fe3b69dec4716bac0f0e856eb95f8c5"
```

The exact file names depend on the repository's actual values-file layout.

### Relationship with Argo CD

The workflow updates Git, not the running workload directly. In a GitOps model, Argo CD observes the updated GitOps repository and reconciles the cluster to match the declared configuration, assuming the application is configured to track those files and the relevant synchronization settings permit it.

### Important assumptions and limitations

- The GitOps repository uses the expected directory structure.
- The values files contain a line matching `tag:.*`.
- The token can push to `main`.
- The caller supplies the intended environment suffix.
- If `values-file-env` is empty, the glob becomes `values-*.yaml`; this may match more files than intended. The caller should supply a valid environment value.
- The `sed` expression replaces every line matching `tag:.*` in each matching file, not a specific image field. Review the values-file structure to ensure that this is safe.
- The commit message includes `[skip ci]` to help avoid triggering another CI run when the repository honors that convention.

---

## Workflow 3: Build a Docker image and push to Harbor

**Workflow name:** `CI - Build Docker Image & Push to Container Registry`

**Purpose:** Check whether an image for the current commit already exists in Harbor. If it does not, check out the code, build a Docker image, and push it to the private Harbor registry.

### Inputs

| Input | Required | Purpose |
|---|---:|---|
| `runs-on` | Yes | Runner label, such as `ubuntu-latest`; the job expression falls back to `ubuntu-latest` if empty. |
| `project-name` | Yes | Project identifier used in the Harbor image name and Dockerfile path. |

### Secrets

| Secret | Required | Purpose |
|---|---:|---|
| `CONT_REG_USERNAME` | Yes | Username used to authenticate to Harbor. |
| `CONT_REG_PASSWORD` | Yes | Password used to authenticate to Harbor. |
| `ALL_REPOS_READONLY` | Yes | Token used to check out source code and private submodules. |

### Permissions

```yaml
permissions:
  id-token: write
```

The shown workflow uses registry credentials stored as secrets. The OIDC permission is configured, but the displayed steps do not use OIDC to authenticate to Harbor.

### Image naming convention

The workflow uses this image reference:

```text
harbor.star-com.net/starcom/<project-name>:<github.sha>
```

For example:

```text
harbor.star-com.net/starcom/tracker-api:2ef299632fe3b69dec4716bac0f0e856eb95f8c5
```

The Git commit SHA is used as the image tag, tying the image to the source revision that produced it.

### Execution steps

1. **Log in to Harbor**
   - Uses `docker/login-action@v3`.
   - Authenticates to `harbor.star-com.net` with the supplied registry credentials.

2. **Check whether the image exists**
   - Sends an authenticated request to Harbor's Docker Registry API for the manifest associated with the current commit SHA.
   - Stores `true` or `false` in the `image-check` step output.
   - Later build steps run only when the output is `false`.

3. **Checkout code if the image is missing**
   - Uses `actions/checkout@v4`.
   - Checks out submodules.
   - Uses full history (`fetch-depth: 0`).
   - Uses `ALL_REPOS_READONLY` as the checkout token.

4. **Set up Docker Buildx**
   - Uses `docker/setup-buildx-action@v3`.
   - Runs only when the image does not already exist.

5. **Test Harbor connectivity**
   - Requests the registry catalog endpoint.
   - Uses `|| true`, so this diagnostic step does not fail the job if the request fails.

6. **Build the Docker image**
   - Runs only when the image is missing.
   - Uses the Dockerfile:
     `./docker-files/Dockerfile.<project-name>.prod`
   - Builds without using the Docker build cache (`--no-cache`).
   - Tags the image with the full commit SHA.

7. **Push the Docker image**
   - Pushes the tagged image to Harbor.
   - Runs only when the image was not found before the build.

### Why check whether the image already exists?

The existence check is intended to avoid rebuilding and pushing an image for the same project and commit SHA more than once. This can save time and avoid duplicate work on repeated workflow runs.

### Important assumptions and limitations

- The Dockerfile exists at `./docker-files/Dockerfile.<project-name>.prod`.
- The Harbor project and repository path `starcom/<project-name>` exist and are accessible.
- Harbor permits the supplied credentials to read manifests and push images.
- The runner has Docker available.
- The current implementation treats any unsuccessful manifest request as “image does not exist.” A network error, authentication error, or server error can therefore lead to an unnecessary build attempt rather than a clear distinction between “not found” and “request failed.”
- The diagnostic catalog request is allowed to fail because of `|| true`; it is not a definitive connectivity gate.
- The `curl -u` approach passes credentials to curl through a command argument. Consider a safer credential-handling pattern and ensure secrets are never printed in logs.

---

## Workflow 4: Send a Discord notification

**Workflow name:** `Discord Notification`

**Purpose:** Receive job results from a calling workflow, determine the overall pipeline status, and send a formatted Discord embed through a webhook.

This workflow is a notification mechanism. It does not build an application, deploy a service, or change the GitOps repository, its just send notification to Discord with the pipeline status.

### Inputs

| Input | Required | Purpose |
|---|---:|---|
| `project-name` | Yes | Application name displayed in the Discord notification. |
| `environment` | Yes | Environment label displayed in the notification. |
| `job-results` | Yes | JSON string containing the calling workflow's `needs` context, normally passed as `${{ toJSON(needs) }}`. |

### Secret

| Secret | Required | Purpose |
|---|---:|---|
| `DISCORD_WEBHOOK_URL` | Yes | Discord webhook URL used to post the notification. |

### Permissions and runner

The job runs on `ubuntu-latest`. Unlike the first three workflows, this workflow does not declare a `permissions` block. Its displayed steps do not require repository write access or cloud authentication; they use the supplied webhook secret to send a message.

### How the calling workflow supplies job results

A caller commonly uses a structure like this:

```yaml
discord-notify:
  name: Notify Discord
  needs: [build-release, update-argocd-image-sha]
  if: ${{ always() }}
  uses: Star-Communications/centralized-repo/.github/workflows/discord-notification.yml@main
  with:
    project-name: tracker-api
    environment: ${{ inputs.argocd-values-env || github.ref_name }}
    job-results: ${{ toJSON(needs) }}
  secrets:
    DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
```

This is an example of how a caller could invoke the workflow; the repository, workflow path, branch, inputs, and job names must match the actual configuration. The `always()` condition is important when the notification should run even after a dependency fails or is cancelled.

### Execution steps

1. **Determine pipeline status**
   - Receives the JSON job results through the `JOB_RESULTS` environment variable.
   - Uses `jq` to inspect each job's `result`.
   - Chooses a status and Discord embed color:
     - `FAILURE` if any job result is `failure`.
     - `CANCELLED` if no failure exists but at least one job is `cancelled`.
     - `SUCCESS` if there is at least one job and all results are `success`.
     - `INCOMPLETE` for other cases, including an empty result set or unexpected result values.

2. **Build the Discord payload**
   - Uses `jq -n` to construct a JSON payload.
   - Includes a Discord embed title, description with the workflow-run link, color, timestamp, and fields.

3. **Send the notification**
   - Verifies that `DISCORD_WEBHOOK_URL` is not empty.
   - Sends the JSON payload to Discord using `curl`.
   - Uses `--fail-with-body`, `--silent`, and `--show-error`.
   - Retries the request up to two times.

### Information included in the notification

The embed includes:

- Overall status and project name in the title.
- A link to the GitHub Actions run.
- Repository.
- Branch or pull-request source branch.
- Commit title, with a fallback if no title is available.
- Short commit SHA (first seven characters).
- User or actor who triggered the workflow.
- Environment.
- Each supplied job's name and result.
- A timestamp generated by `jq`.

### Status and color behavior

| Status | Condition | Embed color |
|---|---|---:|
| `FAILURE` | At least one job has result `failure`. | `15158332` (red) |
| `CANCELLED` | No failures, but at least one job has result `cancelled`. | `9807270` (gray) |
| `SUCCESS` | One or more jobs exist and all have result `success`. | `3066993` (green) |
| `INCOMPLETE` | Any other combination. | `9807270` (gray) |

### Important assumptions and limitations

- The caller passes valid JSON in `job-results`.
- The `job-results` input represents the jobs the caller wants to report. It does not automatically discover every job in the caller's workflow.
- The caller's `needs` list must include the jobs whose results should affect the status.
- The notification job should use `if: ${{ always() }}` if it must run after a failed or cancelled dependency.
- The workflow requires `jq` and `curl`, which are available on the specified Ubuntu runner.
- A webhook URL is a secret. Do not hardcode it in workflow files or print it in logs.
- The current status logic prioritizes failure over cancellation. A workflow with both a failed job and a cancelled job is reported as `FAILURE`.

---

## How the workflows fit together

For a containerized application, the intended high-level flow can be:

1. The caller invokes the Docker build workflow to build and push an image tagged with the source commit SHA.
2. After the image is available, the caller invokes the GitOps update workflow to change the relevant Helm values file to that SHA.
3. The caller invokes the Discord notification workflow after the relevant jobs finish, reporting their outcomes.

For a static frontend, the caller invokes the Node.js-to-S3 workflow instead of the Docker build and GitOps update workflows, then sends a Discord notification when appropriate.

### Example dependency graph

```text
Containerized application
          |
          v
  Build and push image
          |
          v
 Update GitOps image SHA
          |
          v
  Discord notification

Static frontend
          |
          v
 Build Node.js project
          |
          v
       Upload S3
          |
          v
  Discord notification
```

The diagram describes a typical orchestration pattern. The actual dependency order is defined in the caller workflow, not by these reusable workflows themselves.

---

## Security and permissions

Follow these practices when calling or maintaining the workflows:

- **Use GitHub Actions secrets** for registry credentials, repository tokens, and Discord webhook URLs.
- **Use least-privilege tokens.** `ALL_REPOS_READONLY` should only read the repositories and submodules required by checkout. `ARGOCD_REPO_TOKEN` should have only the permissions needed to update the GitOps repository.
- **Restrict AWS role trust.** Configure the AWS IAM role to trust only the intended GitHub repository/workflow identity and apply least-privilege S3 permissions.
- **Use OIDC for AWS authentication.** Avoid long-lived AWS access keys when role assumption through OIDC is available.
- **Protect deployment branches.** Ensure only approved workflows and authorized users can update the GitOps branch or deploy to production.
- **Avoid logging credentials.** Do not echo tokens, passwords, or webhook URLs.
- **Review destructive synchronization.** The S3 command uses `--delete`, so verify the source directory and destination path before running it.
- **Pin dependencies appropriately.** For stronger supply-chain controls, consider pinning third-party actions to verified full commit SHAs in accordance with your organization's policy.

---

## Operational considerations and limitations

Before adopting these workflows across many projects, consider the following improvements:

1. **Validate inputs.** Check that environment names, project names, and destination paths are expected values before performing deployment actions.
2. **Make build assumptions configurable.** The S3 workflow could accept install command, build command, and output-directory inputs if projects differ.
3. **Handle Harbor API errors distinctly.** Treat an HTTP `404` as an absent image, while failing clearly on authentication, connectivity, and server errors.
4. **Validate the expected GitOps file.** Fail with a clear message if no values files match, rather than silently completing without updating a tag.
5. **Update only the intended YAML field.** A YAML-aware tool or a narrowly scoped replacement is safer than replacing every line matching `tag:.*`.
6. **Use explicit environment controls.** Prefer validated environment inputs over relying on `github.ref_name` for every deployment scenario.
7. **Ensure notifications cover the intended jobs.** Check that `needs` and the caller's `if` condition match the desired success/failure/cancellation behavior.
8. **Test changes in a non-production environment** before using the workflows for production deployment.

These are recommendations for hardening and clarity; they do not imply that the current workflows are necessarily failing.

---

## Example caller workflow

The following is an illustrative example showing how a caller can invoke the Docker build workflow and then send a Discord notification. Replace the branch reference, project values, and secrets with those appropriate for your repository.

```yaml
name: Example CI/CD

on:
  push:
    branches:
      - main

jobs:
  build-release:
    uses: Star-Communications/centralized-repo/.github/workflows/ci-build-and-push-image.yml@main
    with:
      runs-on: ubuntu-latest
      project-name: tracker-api
    secrets:
      CONT_REG_USERNAME: ${{ secrets.CONT_REG_USERNAME }}
      CONT_REG_PASSWORD: ${{ secrets.CONT_REG_PASSWORD }}
      ALL_REPOS_READONLY: ${{ secrets.ALL_REPOS_READONLY }}

  notify:
    needs: [build-release]
    if: ${{ always() }}
    uses: Star-Communications/centralized-repo/.github/workflows/discord-notification.yml@main
    with:
      project-name: tracker-api
      environment: ${{ github.ref_name }}
      job-results: ${{ toJSON(needs) }}
    secrets:
      DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
```

This example shows only the image-build and notification stages. To add the GitOps update stage, define it as a separate job dependent on the image-build job and configure the appropriate `gitOps-project-name`, `values-file-env`, and `ARGOCD_REPO_TOKEN` values. For a frontend, call the S3 workflow with its required inputs and secret instead.

---

## Troubleshooting

| Symptom | Possible cause | What to check |
|---|---|---|
| `npm run install:all` fails | The script is missing or fails in the current directory. | Check `package.json`, workspace layout, and lockfiles. |
| S3 sync cannot find `./dist` | Build output is elsewhere or build failed to produce assets. | Verify the build script and output directory. |
| AWS role assumption fails | OIDC trust policy or role ARN is incorrect. | Check GitHub OIDC trust conditions, IAM permissions, and `aws-role`. |
| No GitOps values files are updated | Environment suffix or project folder does not match. | Verify the inputs and the `k8s/manifests/starcom-projects/` directory. |
| GitOps push is rejected | Token lacks permission or branch protection blocks the push. | Check token access and repository branch rules. |
| Docker build fails | Dockerfile path, build context, or dependencies are wrong. | Verify `docker-files/Dockerfile.<project-name>.prod` and the Docker build context. |
| Image build runs even though an image exists | The manifest check did not successfully identify the existing image. | Inspect Harbor response status and authentication. |
| Discord notification reports `INCOMPLETE` | Job results are empty or contain a result other than the expected values. | Inspect the caller's `needs` and `toJSON(needs)` payload. |
| Discord notification is skipped after a failure | The caller's notification job may not use `if: ${{ always() }}`. | Review the caller job's condition and `needs` list. |
| Discord webhook request fails | Secret is missing, invalid, or Discord is unavailable. | Check secret configuration and HTTP response without exposing the webhook URL. |

---

## Summary

These four reusable workflows provide separate building blocks for delivery automation:

- **Node.js to S3:** builds a static frontend and syncs its output to an S3 path.
- **Docker to Harbor:** builds and pushes a container image tagged with the source commit SHA, skipping the build when the image is detected.
- **GitOps update for Argo CD:** changes the image tag in the GitOps repository so Argo CD can reconcile the deployment.
- **Discord notification:** evaluates caller-provided job results and posts a success, failure, cancelled, or incomplete status.

The calling workflow connects these building blocks by defining triggers, inputs, secrets, and job dependencies.
