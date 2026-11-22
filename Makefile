SHELL := /usr/bin/env bash

.PHONY: help deps preflight validate test build clean

help:
	@echo 'deps     Install Fedora build-host dependencies'
	@echo 'preflight Check host, KVM, input ISO and free space'
	@echo 'validate Run static project checks, documentation checks and unit tests'
	@echo 'test     Run hardware-independent Python unit tests only'
	@echo 'build    Build the ISO (requires FEDORA_INSTALL_ISO and root)'
	@echo 'clean    Remove generated build output'

deps:
	bash build/install-host-deps.sh

preflight:
	@test -n "$(FEDORA_INSTALL_ISO)" || (echo 'Set FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso' >&2; exit 2)
	sudo -E env FEDORA_INSTALL_ISO="$(FEDORA_INSTALL_ISO)" bash build/preflight.sh

validate:
	bash build/validate.sh

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

build:
	@test -n "$(FEDORA_INSTALL_ISO)" || (echo 'Set FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso' >&2; exit 2)
	sudo -E env FEDORA_INSTALL_ISO="$(FEDORA_INSTALL_ISO)" bash build/build-iso.sh

clean:
	rm -rf out
