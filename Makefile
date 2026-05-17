SHELL := /bin/bash

UV ?= uv
STANDALONE_PYTHON ?= python3
PYTHON_VERSION ?= 3.11
VENV ?= .venv
PROJECT_NAME ?= Home Assistant MQTT Agent
CLI_NAME ?= ha-mqtt-agent
PACKAGE_NAME ?= ha_mqtt_agent
CONFIG_NAME ?= ha-mqtt-agent
PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
INSTALL_PATH ?= $(BINDIR)/$(CLI_NAME)
APP_HOME ?= $(HOME)/.local/share/$(CLI_NAME)
APP_VENV ?= $(APP_HOME)/venv
APP_PYTHON ?= $(APP_VENV)/bin/python
CONFIG_DIR ?= $(HOME)/.config/$(CONFIG_NAME)
CONFIG_PATH ?= $(CONFIG_DIR)/config.toml
MARKDOWN_FILES := README.md CHANGELOG.md TODO.md AGENTS.md docs/*.md

.DEFAULT_GOAL := help

.PHONY: help check-deps check-install-deps sync install install-dev install-link install-config install-agent uninstall-agent restart-agent agent-status uninstall lint test check run clean

help: ## Show available targets
	@awk 'BEGIN { FS = ":.*##" } /^[a-zA-Z_-]+:.*##/ { printf "  %-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-deps: ## Verify required local tools
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "uv not found"; exit 1; }
	@command -v "$(STANDALONE_PYTHON)" >/dev/null 2>&1 || { echo "$(STANDALONE_PYTHON) not found"; exit 1; }
	@command -v markdownlint >/dev/null 2>&1 || { echo "markdownlint not found"; exit 1; }
	@command -v shellcheck >/dev/null 2>&1 || { echo "shellcheck not found"; exit 1; }
	@$(STANDALONE_PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "$(STANDALONE_PYTHON) must be Python 3.11 or newer")'
	@mkdir -p "$(BINDIR)" "$(CONFIG_DIR)"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "$(BINDIR) is on PATH"; \
	else \
		echo "warning: $(BINDIR) is not on PATH"; \
		echo "add this to your shell profile:"; \
		echo "export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

check-install-deps: ## Verify tools needed for the standalone install
	@command -v "$(STANDALONE_PYTHON)" >/dev/null 2>&1 || { echo "$(STANDALONE_PYTHON) not found"; exit 1; }
	@$(STANDALONE_PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "$(STANDALONE_PYTHON) must be Python 3.11 or newer")'
	@mkdir -p "$(BINDIR)" "$(CONFIG_DIR)"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "$(BINDIR) is on PATH"; \
	else \
		echo "warning: $(BINDIR) is not on PATH"; \
		echo "add this to your shell profile:"; \
		echo "export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

$(VENV)/bin/python: pyproject.toml
	@"$(UV)" sync --extra dev

sync: $(VENV)/bin/python ## Sync the project environment

install: check-install-deps ## Install a standalone user-facing runtime
	@mkdir -p "$(APP_HOME)"
	@rm -rf "$(APP_VENV)"
	@"$(STANDALONE_PYTHON)" -m venv "$(APP_VENV)"
	@"$(APP_PYTHON)" -m pip install --upgrade pip
	@"$(APP_PYTHON)" -m pip install .
	@$(MAKE) install-link install-config

install-dev: check-deps sync ## Link the dev environment CLI into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(abspath $(VENV)/bin/$(CLI_NAME))" "$(INSTALL_PATH)"
	@$(MAKE) install-config
	@echo "Installed editable dev CLI at $(INSTALL_PATH)"

install-link: ## Link the standalone runtime CLI into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(APP_VENV)/bin/$(CLI_NAME)" "$(INSTALL_PATH)"
	@echo "Installed $(CLI_NAME) -> $(INSTALL_PATH)"

install-config: ## Install the example config file if missing
	@mkdir -p "$(CONFIG_DIR)"
	@if [ ! -f "$(CONFIG_PATH)" ]; then \
		cp config.toml.example "$(CONFIG_PATH)"; \
		echo "Installed config template to $(CONFIG_PATH)"; \
	else \
		echo "Config already exists at $(CONFIG_PATH)"; \
	fi

install-agent: install ## Install and start the macOS LaunchAgent
	@./scripts/install-launch-agent.sh

uninstall-agent: ## Stop and remove the macOS LaunchAgent
	@./scripts/uninstall-launch-agent.sh

restart-agent: install-agent ## Restart the macOS LaunchAgent
	@launchctl kickstart -k "gui/$$(id -u)/com.marcomc.ha-mqtt-agent"

agent-status: ## Show the macOS LaunchAgent status
	@launchctl print "gui/$$(id -u)/com.marcomc.ha-mqtt-agent"

uninstall: ## Remove the standalone runtime and user-facing symlink
	@rm -f "$(INSTALL_PATH)"
	@rm -rf "$(APP_HOME)"
	@echo "Removed $(INSTALL_PATH)"
	@echo "Removed $(APP_HOME)"

lint: sync ## Run Python, Markdown, and shell quality checks
	@"$(UV)" run ruff check src tests
	@"$(UV)" run ruff format --check src tests
	@"$(UV)" run mypy src tests
	markdownlint --config .markdownlint.json $(MARKDOWN_FILES)
	shellcheck --enable=all scripts/*.sh

test: sync ## Run the test suite
	@"$(UV)" run pytest -q

check: lint test ## Run the full maintainer quality gate

run: sync ## Show the CLI help from the dev environment
	@"$(UV)" run "$(CLI_NAME)" --help

clean: ## Remove local development artifacts
	rm -rf "$(VENV)" .pytest_cache .mypy_cache .ruff_cache build dist src/*.egg-info *.egg-info
