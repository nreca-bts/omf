#!/bin/bash
# Just kick off a pull request.

# this file's path
THIS_FILES_PATH=$(dirname "$0")

# create the pull request (if you're david)
git -C "$THIS_FILES_PATH/../../" push origin master && gh pr create --repo nreca-bts/omf --base master --head dpinney:master