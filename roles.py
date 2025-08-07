# roles.py

import json
import os

ROLES_FILE = "roles.json"

def load_roles():
    if not os.path.exists(ROLES_FILE):
        return {}
    with open(ROLES_FILE, "r") as f:
        return json.load(f)

def save_roles(data):
    with open(ROLES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def assign_user_to_manager(manager_id, user_id):
    roles = load_roles()
    if manager_id not in roles:
        roles[manager_id] = []
    if user_id not in roles[manager_id]:
        roles[manager_id].append(user_id)
    save_roles(roles)

def get_users_for_manager(manager_id):
    roles = load_roles()
    return roles.get(manager_id, [])
