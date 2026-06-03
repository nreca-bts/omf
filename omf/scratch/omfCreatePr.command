#!/bin/bash
# Just kick off a pull request.

# this repo's path
THIS_FILES_PATH=$(dirname "$0")
REPO_ROOT="$THIS_FILES_PATH/../../"

# try to make it a clean PR
git -C "$REPO_ROOT" fetch upstream
git -C "$REPO_ROOT" rebase upstream/master
git -C "$REPO_ROOT" push --force-with-lease origin master

# create the pull request (if you're david)
git -C "$REPO_ROOT" push origin master && gh pr create --repo nreca-bts/omf --base master --head dpinney:master