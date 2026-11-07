SHELL := /usr/bin/env bash

.PHONY: help deps preflight validate test ui build clean

help:
	@printf '%s\n' \
	  'deps     Install Fedora build-host dependencies' \
	  'preflight Check host, KVM, input ISO and free space' \\\n	  'validate Run static project and Bash syntax checks' \
	  'test     Run hardware-independent Python unit tests' \
	  'ui       Run the read-only dialog storage browser' \
	  'build    Build the ISO (requires FEDORA_INSTALL_ISO and root)' \
	  'clean    Remove generated build output'

deps:
	bash build/install-host-deps.sh

preflight:
	@test -n "$(FEDORA_INSTALL_ISO)" || (echo 'Set FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso' >&2; exit 2)
	sudo -E env FEDORA_INSTALL_ISO="$(FEDORA_INSTALL_ISO)" bash build/preflight.sh

validate:
	bash build/validate.sh

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

ui:
	./scripts/feclora-ui.sh

build:
	@test -n "$(FEDORA_INSTALL_ISO)" || (echo 'Set FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso' >&2; exit 2)
	sudo -E env FEDORA_INSTALL_ISO="$(FEDORA_INSTALL_ISO)" bash build/build-iso.sh

clean:
	rm -rf out
