#!/usr/bin/env bash
# Add settings a release introduced to an existing .env, keeping your values.
#
# Usage:
#     infra/scripts/sync-env.sh [env-file] [template]   # defaults: .env .env.example
#
# Compose reads `env_file: .env`, so a deployment that copied .env.example once
# never gains later settings — it silently keeps running on the code defaults.
# This copies across only the keys your .env is missing, with the comments that
# explain them, after backing the file up.
#
# A key you have already set is never overwritten, so secrets and tuned values
# survive. Keys whose value differs from the template are reported instead, for
# you to decide: turning a feature on is a deployment's call, not a migration's.
# Secret-looking keys are never compared or printed.
#
# Re-running is a no-op.
set -euo pipefail

ENV_FILE="${1:-.env}"
TEMPLATE="${2:-.env.example}"

[ -f "$TEMPLATE" ] || { echo "no template at $TEMPLATE" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "no env file at $ENV_FILE" >&2; exit 1; }

# A key counts as set only when it is live at the start of a line. A key that
# is present but commented out is not in use, so the deployment still needs it.
has_key() { grep -qE "^[[:space:]]*$1=" "$ENV_FILE"; }
# Last wins, matching how compose and dotenv resolve a repeated key.
value_of() { sed -nE "s/^[[:space:]]*$1=(.*)$/\1/p" "$ENV_FILE" | tail -1; }
is_secret() { case "$1" in *SECRET*|*TOKEN*|*PASSWORD*|*_KEY) return 0;; *) return 1;; esac; }

added=0
differs=""
buffer=""     # comments/blank lines seen since the last key, so an added key
to_append=""  # arrives with the text explaining it

while IFS= read -r line || [ -n "$line" ]; do
  if [[ "$line" =~ ^[[:space:]]*([A-Z_][A-Z0-9_]*)= ]]; then
    key="${BASH_REMATCH[1]}"
    template_value="${line#*=}"
    if has_key "$key"; then
      if ! is_secret "$key" && [ "$(value_of "$key")" != "$template_value" ]; then
        differs+="  $key: yours=$(value_of "$key")  template=$template_value"$'\n'
      fi
    else
      to_append+="$buffer$line"$'\n'
      added=$((added + 1))
    fi
    buffer=""
  else
    buffer+="$line"$'\n'
  fi
done < "$TEMPLATE"

if [ "$added" -eq 0 ]; then
  echo "nothing to add — $ENV_FILE already has every key in $TEMPLATE"
else
  backup="$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  cp "$ENV_FILE" "$backup"
  printf '\n%s' "$to_append" >> "$ENV_FILE"
  echo "added $added key(s) to $ENV_FILE  (backup: $backup)"
fi

if [ -n "$differs" ]; then
  echo
  echo "kept your value, template differs — change by hand if you want the new one:"
  printf '%s' "$differs"
fi
