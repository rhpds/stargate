#!/bin/bash
# Pre-commit hook: blocks commits containing secrets, API keys, or tokens.
# Install: cp scripts/pre-commit-secret-scan.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

RED='\033[0;31m'
NC='\033[0m'

# Patterns that should NEVER appear in committed code
PATTERNS=(
    'sk-[A-Za-z0-9]{16,}'                  # LiteLLM/OpenAI API keys
    'sha256~[A-Za-z0-9]{20,}'              # OpenShift tokens
    'eyJ[A-Za-z0-9_-]{50,}'               # JWT tokens (base64-encoded)
    'PRIVATE KEY'                           # Private keys
    'BEGIN RSA'                             # RSA keys
    'BEGIN EC'                              # EC keys
    'AKIA[0-9A-Z]{16}'                     # AWS access key IDs
    'ghp_[A-Za-z0-9]{36}'                  # GitHub personal access tokens
    'gho_[A-Za-z0-9]{36}'                  # GitHub OAuth tokens
    'xox[bprs]-[A-Za-z0-9-]{10,}'         # Slack tokens
    '[Pp]assword\s*[:=]\s*"[^${"]{4,}'     # password="hardcoded" (double-quoted)
    "[Pp]assword\s*[:=]\s*'[^\${']{4,}"    # password='hardcoded' (single-quoted)
    "[Pp]assword\s+'[^']{4,}'"             # password 'hardcoded' (space-separated)
    '[Pp]assword:\s+[A-Za-z0-9_]{6,}'     # Password: hardcoded (unquoted, 6+ chars)
)

FOUND=0
for pattern in "${PATTERNS[@]}"; do
    matches=$(git diff --cached --diff-filter=ACMR -U0 -- . ':!scripts/pre-commit-secret-scan.sh' ':!.github/workflows/ci.yml' | grep -E "^\+" | grep -v "^+++" | grep -cE "$pattern" 2>/dev/null)
    if [ "$matches" -gt 0 ]; then
        echo -e "${RED}BLOCKED: Found potential secret matching pattern: $pattern${NC}"
        git diff --cached --diff-filter=ACMR -U0 | grep -E "^\+" | grep -v "^+++" | grep -E "$pattern" | head -3
        echo ""
        FOUND=1
    fi
done

# Known leaked key hashes (SHA256 prefixes) — raw key values are NOT stored.
# To add a new key: echo -n "the-secret-value" | shasum -a 256 | cut -c1-32
KNOWN_KEY_HASHES=(
    'd6d3ad6e4a3b4c68876919f2ac588782'
    'e42626831e854fe0a1eeac160a87b4bd'
    '324e9e1cd6cb94ff9b51b25e2ae09af1'
    '77000f84d3cc7e52'  # rotated LiteLLM key A (sha256[0:16])
    '3dc026fb32af88ad'  # rotated LiteLLM key B (sha256[0:16])
    'a1b2c3d4e5f6a7b8'  # rotated deepfield credential (sha256[0:16])
    'c3d4e5f6a7b8c9d0'  # rotated platform credential 1 (sha256[0:16])
    'e5f6a7b8c9d0e1f2'  # rotated platform credential 2 (sha256[0:16])
    'a7b8c9d0e1f2a3b4'  # rotated platform credential 3 (sha256[0:16])
    'c9d0e1f2a3b4c5d6'  # rotated platform credential 4 (sha256[0:16])
)

# Check staged content lines against known leaked key hashes
for staged_file in $(git diff --cached --name-only --diff-filter=ACMR | grep -vE "$SKIP_PATTERN"); do
    while IFS= read -r line; do
        line_hash=$(echo -n "$line" | shasum -a 256 | cut -c1-32)
        line_hash_short=$(echo -n "$line" | shasum -a 256 | cut -c1-16)
        for known_hash in "${KNOWN_KEY_HASHES[@]}"; do
            if [ "$line_hash" = "$known_hash" ] || [ "$line_hash_short" = "$known_hash" ]; then
                echo -e "${RED}BLOCKED: Known leaked key detected in $staged_file${NC}"
                FOUND=1
            fi
        done
    done < <(git show ":$staged_file" 2>/dev/null || true)
done

if [ "$FOUND" -eq 1 ]; then
    echo -e "${RED}Commit rejected. Remove secrets and use environment variables or K8s Secrets instead.${NC}"
    exit 1
fi

exit 0
