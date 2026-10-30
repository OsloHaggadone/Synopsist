#!/bin/sh
# Push the website's songs to the private repository OsloHaggadone/synopsist-audio, before pushing main:
# player/library/audio/ is its clone, kept out of the public repositories, and the site's publishing
# takes the songs from there (and won't publish if one the song list names is missing). Songs added or
# removed by scripts/build_catalog.py go in one commit. Run it from ~/OsloHaggadone:
#   sh Synopsist/scripts/push_songs.sh
# Its key (~/.ssh/synopsist_audio, set in that clone's core.sshCommand) is a deploy key that opens that
# repository only.
set -e
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/Synopsist/player/library/audio"
git add -A
if git diff --cached --quiet; then
  echo "No song changes to save."
else
  added=$(git diff --cached --name-only --diff-filter=A -- '*.mp3' | wc -l)
  removed=$(git diff --cached --name-only --diff-filter=D -- '*.mp3' | wc -l)
  git commit -q -m "Songs: $added added, $removed removed"
fi
git push -q origin main
echo "The private songs repository is up to date: https://github.com/OsloHaggadone/synopsist-audio"
