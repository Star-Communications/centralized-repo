# Centralized Repo

Centralized organization repository which contains:

- reusable Github actions to be used by other repositories in the organization.
- utilities docker-compose files (e.g. web servers, databases, etc.)
- reusable pre-commit hooks to be used by other repositories in the organization.

# Centralized Pre-Commit Formatter

This repository provides a custom pre-commit formatter script that can be used across multiple repositories to ensure consistent code formatting.

## Setting Up Pre-Commit Formatter in Other Repositories

1. **Add `.pre-commit-config.yaml`**:
   Copy the following configuration file into the root of your target repository:

   ```yaml
   repos:
     - repo: https://github.com/your-username/centralized-repo
       rev: main # Use the branch or tag where the script is located
       hooks:
         - id: custom-formatter
           name: Custom Pre-Commit Formatter
           entry: python scripts/pre_commit_formatter.py
           language: system
           files: ".*" # Apply to all files
   ```

   Replace `https://github.com/your-username/centralized-repo` with the actual URL of this repository.

2. **Install Pre-Commit**:
   Install the `pre-commit` tool if it is not already installed:

   ```bash
   pip install pre-commit
   ```

3. **Install Hooks**:
   Run the following command in the target repository to install the pre-commit hooks:

   ```bash
   pre-commit install
   ```

4. **Run the Formatter**:
   To test the formatter on all files in the repository, run:
   ```bash
   pre-commit run --all-files
   ```

## Requirements

Ensure the following tools are installed on your system:

- `python` (for running the custom script)
- `dotnet format` (for `.cs` and `.csproj` files)
- `Prettier` (for `.vue`, `.js`, `.html`, and `.css` files)
- `yamllint` (for `.yml` files)
- `xmllint` (for `.xml` files)

## Updating the Formatter Script

If you update the `pre_commit_formatter.py` script in this repository, ensure you update the `rev` field in the `.pre-commit-config.yaml` file of the target repositories to point to the latest commit or tag.
