# eSimMate - Agent Development Instructions

## Project
eSimMate is a Python-based Automated Tool & Dependency Manager for eSim.

## Screening Task
FOSSEE eSim Semester Long Internship - Autumn 2026
Screening Task 5: Tool Manager (CSE and related fields)

## Primary Requirements
The implementation must strongly satisfy:

1. Tool Installation Management
5. User Interface

The prototype must demonstrate:
- Tool detection
- Installed version detection
- Version comparison
- Tool installation
- User-friendly CLI
- Action logging

## Secondary Features
Where practical, support:
- OS detection
- Architecture detection
- Package-manager detection
- Dependency checking
- Configuration/path checking
- Dry-run mode
- Error handling
- Automated testing

## Technology
- Python 3.10–3.12.x
- Typer for CLI
- PyYAML for configuration
- pytest for testing
- Standard Python libraries wherever possible
- PyQt6 only if a GUI is added later

## Architecture Requirements
Use modular, maintainable Python architecture.

Do NOT put the entire application into one Python file.

Use:
- Tool abstraction
- Package-manager abstraction
- Version manager
- System detector
- Configuration manager
- Logging manager
- CLI command modules

Use SOLID principles where appropriate.

## Safety Requirements
Never silently execute privileged commands.

Installation commands must:
- Support dry-run
- Show the command before execution
- Ask for confirmation before privileged installation
- Handle permission errors gracefully
- Never delete or modify unrelated files

Never use:
- os.system() for arbitrary commands
- shell=True unless absolutely necessary and justified

Prefer subprocess.run() with argument lists.

## Testing
Every major module must have unit tests.

The implementation must support testing without actually installing software.

Use mocks for package-manager commands where appropriate.

## Documentation
Maintain:
- README.md
- Architecture documentation
- Installation instructions
- Testing documentation
- Design document

## Code Quality
- Type hints
- Docstrings for public APIs
- Meaningful variable names
- Small functions
- Error handling
- No hard-coded absolute paths
- No hard-coded user-specific paths
- No API keys or secrets

## Development Workflow
Do not implement the entire project at once.

Follow:
1. Research
2. Requirements analysis
3. Architecture
4. Project scaffolding
5. Core abstractions
6. Detection
7. Version management
8. Installation
9. CLI
10. Logging
11. Testing
12. Documentation
13. Final verification

Before implementing a major feature, explain the proposed design and verify it against the task requirements.