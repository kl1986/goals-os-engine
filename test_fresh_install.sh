#!/usr/bin/env bash
# Integration test for the Goals OS fresh installation pipeline.
# This script simulates onboarding a new user by cloning the brain template,
# initializing it with onboard.py, and running a complete capture -> triage -> execute loop.

set -e # Exit immediately if a command exits with a non-zero status

echo "Starting Fresh Install Verification..."

# 1. Create a temporary directory for the clone
TEMP_DIR=$(mktemp -d -t goals-os-test.XXXXXX)
echo "Created temporary directory at: $TEMP_DIR"

# Clean up on exit
trap 'rm -rf "$TEMP_DIR"' EXIT

# Paths
ENGINE_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$ENGINE_DIR")/goals-os-brain-template"
CLONED_BRAIN="$TEMP_DIR/brain"

echo "Engine directory: $ENGINE_DIR"
echo "Template directory: $TEMPLATE_DIR"

# 2. Clone the template
echo "Cloning brain template..."
cp -R "$TEMPLATE_DIR" "$CLONED_BRAIN"

# Ensure we're in the engine dir
cd "$ENGINE_DIR"

# 3. Run onboard.py
echo "Running onboard.py to initialize configuration and an Area..."
PYTHONPATH=. python3 scripts/onboard.py \
    --brain "$CLONED_BRAIN" \
    --area-name "Personal Development" \
    --area-agent "Personal" \
    --area-slug "personal-dev" \
    --review-window-days 7 \
    --graduation-min-sessions 3

# 4. Verify structural soundness
echo "Verifying structural soundness..."
if [ ! -d "$CLONED_BRAIN/config" ]; then
    echo "Error: config/ directory not found."
    exit 1
fi

if [ ! -d "$CLONED_BRAIN/areas/personal-dev" ]; then
    echo "Error: areas/personal-dev/ directory not found."
    exit 1
fi
echo "Structure looks good."

# 5. Run a mock capture → triage → execute loop on blank state
echo "Running mock capture..."
MOCK_SOURCE="mock-source"
RAW_DIR="$CLONED_BRAIN/inbox/raw/$MOCK_SOURCE"
mkdir -p "$RAW_DIR"
MOCK_CAPTURE="$RAW_DIR/buy-milk.md"
echo "Buy milk" > "$MOCK_CAPTURE"

# Inject a routing rule so triage resolves Pass A
echo "Injecting Pass A routing rule..."
cat << EOF >> "$CLONED_BRAIN/config/routing-rules.md"

if: source == "$MOCK_SOURCE" and contains("milk")
then: route -> areas/personal-dev/_memory.md
confidence: High
EOF

echo "Running triage.py..."
PYTHONPATH=. python3 scripts/triage.py --brain "$CLONED_BRAIN" --source "$MOCK_SOURCE"

PLAN_FILE=$(ls "$CLONED_BRAIN/inbox/triage/"*.md | head -n 1)

if [ -z "$PLAN_FILE" ]; then
    echo "Error: Triage plan not found."
    exit 1
fi

echo "Ticking the plan so it executes..."
# Replace '| [ ] |' with '| [x] |'
python3 -c "import sys; p=sys.argv[1]; text=open(p).read(); open(p, 'w').write(text.replace('| [ ] |', '| [x] |'))" "$PLAN_FILE"

echo "Running execute.py..."
PYTHONPATH=. python3 scripts/execute.py --brain "$CLONED_BRAIN" --plan "$PLAN_FILE"

echo "Verifying execute output..."
if grep -q "Buy milk" "$CLONED_BRAIN/areas/personal-dev/_memory.md"; then
    echo "Capture successfully routed to memory."
else
    echo "Error: Capture not found in destination."
    exit 1
fi

echo "Mock loop completed successfully."
echo "Fresh Install Verification Passed!"
