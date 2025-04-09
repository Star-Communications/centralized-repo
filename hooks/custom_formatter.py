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
    else:
        # Add logic to format the file based on its type
        print(f"Formatting file: {file_path}")
        # Example: Add specific formatting rules here
        # ...

def main():
    print("Custom formatter script started.")
    if len(sys.argv) < 2:
        print("No files provided for formatting.")
        sys.exit(1)

    for file_path in sys.argv[1:]:
        if os.path.exists(file_path):
            format_file(file_path)
        else:
            print(f"File not found: {file_path}")
    print("Custom formatter script completed.")

if __name__ == "__main__":
    main()
