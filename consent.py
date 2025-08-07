import json
import os

# File where consented user IDs are saved
CONSENT_FILE = "consent.json"

# Load consented user IDs from disk
def load_consents():
    if not os.path.exists(CONSENT_FILE):
        return set()
    with open(CONSENT_FILE, "r") as f:
        return set(json.load(f))

# Save updated consent list to disk
def save_consents(consents):
    with open(CONSENT_FILE, "w") as f:
        json.dump(list(consents), f)

# Add user to the consent list
def add_consent(user_id):
    consents = load_consents()
    consents.add(user_id)
    save_consents(consents)

# Remove user from consent list
def remove_consent(user_id):
    consents = load_consents()
    if user_id in consents:
        consents.remove(user_id)
        save_consents(consents)

# Check if user is opted-in
def has_consented(user_id):
    return user_id in load_consents()
