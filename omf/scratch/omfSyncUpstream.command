#!/bin/bash
# This script synchronizes the local repository with the upstream repository.

set -e

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir/.."

git remote add upstream https://github.com/nreca-bts/omf.git || true
git fetch upstream
git checkout master
git reset --hard upstream/master
git push --force-with-lease origin master

# Pause so output can be reviewed before the script exits (only when running in a terminal)
if [ -t 1 ]; then
	trap 'echo; read -r -p "Press Enter to exit..."' EXIT
fi