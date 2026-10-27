#!/bin/sh
# Copy Synopsist to its own repository, github.com/OsloHaggadone/Synopsist: this folder's history only
# (git subtree split), so the project shows on the profile by itself. The site is still published from
# the portfolio's repository (OsloHaggadone/oslohaggadone.github.io); GitHub Pages stays off in the
# Synopsist one, or it would take over oslohaggadone.github.io/Synopsist/. Run it after pushing main:
#   sh Synopsist/scripts/push_synopsist_repo.sh      (from ~/OsloHaggadone)
# Its key (~/.ssh/synopsist_repo) is a deploy key that opens that repository only.
set -e
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
split=$(git subtree split --prefix=Synopsist)  # the same commits each time, so later pushes just add to them
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/synopsist_repo -o IdentitiesOnly=yes" \
  git push git@github.com:OsloHaggadone/Synopsist.git "$split:refs/heads/main"
echo "Synopsist's own repository is up to date: https://github.com/OsloHaggadone/Synopsist"
