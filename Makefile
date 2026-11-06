SHELL := /usr/bin/env bash

.PHONY: help deps build clean

help:
	@printf '%s\n' \
	  'deps   Install Fedora build-host dependencies' \
	  'build  Build the ISO (requires FEDORA_INSTALL_ISO and root)' \
	  'clean  Remove generated build output'

deps:
	bash build/install-host-deps.sh

build:
	@test -n "$(FEDORA_INSTALL_ISO)" || (echo 'Set FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso' >&2; exit 2)
	sudo -E env FEDORA_INSTALL_ISO="$(FEDORA_INSTALL_ISO)" bash build/build-iso.sh

clean:
	rm -rf out
