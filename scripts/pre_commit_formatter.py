import os
import subprocess
import sys

# Define file extensions and their respective format commands
FORMATTERS = {
    ".cs": "dotnet format {file}",
    ".csproj": "dotnet format {file}",
    ".vue": "prettier --write {file}",
    ".js": "prettier --write {file}",
    ".html": "prettier --write {file}",
    ".css": "prettier --write {file}",
    ".yml": "yamllint -f parsable {file}",
    ".xml": "xmllint --format {file} --output {file}"
}

def format_file(file_path):
    _, ext = os.path.splitext(file_path)
    if ext in FORMATTERS:
        command = FORMATTERS[ext].format(file=file_path)
        try:
            print(f"Formatting {file_path}...")
            subprocess.run(command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error formatting {file_path}: {e}")
            sys.exit(1)

def main():
    # Get the list of staged files
    result = subprocess.run("git diff --cached --name-only", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("Failed to get staged files.")
        sys.exit(1)

    staged_files = result.stdout.strip().split("\n")
    for file_path in staged_files:
        if os.path.isfile(file_path):
            format_file(file_path)

if __name__ == "__main__":
    main()
