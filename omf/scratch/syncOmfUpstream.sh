#!/bin/bash
# This script synchronizes the local repository with the upstream repository.

set -e

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir/.."

git remote add upstream https://github.com/nreca-bts/omf.git
git fetch upstream
git checkout master
git reset --hard upstream/master
git push --force-with-lease origin master