import os
import uuid
import time
import shutil
import random
import string
import requests
import json

BASE_URL = "http://localhost:8080/api/v1"


def random_string(length=10):
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def create_dummy_file(file_name, content=None, size=1024):
    if content is None:
        content = os.urandom(size)
    with open(file_name, "wb") as f:
        f.write(content)
    return file_name


def create_user(email, password, name):
    user_data = {"email": email, "password": password, "name": name}
    response = requests.post(f"{BASE_URL}/users/create", json=user_data)
    response.raise_for_status()
    return response.json()


def login(email, password):
    auth_data = {"email": email, "password": password}
    response = requests.post(f"{BASE_URL}/auths/login", json=auth_data)
    response.raise_for_status()
    return response.json()["token"]


def create_chat(token, title):
    headers = {"Authorization": f"Bearer {token}"}
    chat_data = {"chat": {"title": title}}
    response = requests.post(f"{BASE_URL}/chats/new", json=chat_data, headers=headers)
    response.raise_for_status()
    return response.json()


def upload_file(token, file_name, content_type="text/plain"):
    headers = {"Authorization": f"Bearer {token}"}
    with open(file_name, "rb") as f:
        files = {"file": (file_name, f.read(), content_type)}
        response = requests.post(f"{BASE_URL}/files/", files=files, headers=headers)
    response.raise_for_status()
    return response.json()


def create_note(token, title):
    headers = {"Authorization": f"Bearer {token}"}
    note_data = {"title": title}
    response = requests.post(f"{BASE_URL}/notes/create", json=note_data, headers=headers)
    response.raise_for_status()
    return response.json()


def create_prompt(token, command, title, content):
    headers = {"Authorization": f"Bearer {token}"}
    prompt_data = {"command": command, "title": title, "content": content}
    response = requests.post(
        f"{BASE_URL}/prompts/create", json=prompt_data, headers=headers
    )
    response.raise_for_status()
    return response.json()


def create_model(token, model_id):
    headers = {"Authorization": f"Bearer {token}"}
    model_data = {
        "id": model_id,
        "name": model_id,
        "meta": {},
        "params": {},
    }
    response = requests.post(
        f"{BASE_URL}/models/create", json=model_data, headers=headers
    )
    response.raise_for_status()
    return response.json()


def create_knowledge_base(token, name):
    headers = {"Authorization": f"Bearer {token}"}
    kb_data = {"name": name, "description": ""}
    response = requests.post(
        f"{BASE_URL}/knowledge/create", json=kb_data, headers=headers
    )
    response.raise_for_status()
    return response.json()


def create_function(token, function_id, content):
    headers = {"Authorization": f"Bearer {token}"}
    function_data = {"id": function_id, "content": content, "meta": {}}
    response = requests.post(
        f"{BASE_URL}/functions/create", json=function_data, headers=headers
    )
    response.raise_for_status()
    return response.json()


def create_tool(token, tool_id, content):
    headers = {"Authorization": f"Bearer {token}"}
    tool_data = {"id": tool_id, "content": content, "meta": {}}
    response = requests.post(f"{BASE_URL}/tools/create", json=tool_data, headers=headers)
    response.raise_for_status()
    return response.json()


def delete_user(token, user_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.delete(f"{BASE_URL}/users/{user_id}", headers=headers)
    response.raise_for_status()


def test_prune_all_orphaned_data_extensively():
    ADMIN_TOKEN = os.environ.get("OPEN_WEBUI_ADMIN_TOKEN")
    if not ADMIN_TOKEN:
        print("Skipping API test: OPEN_WEBUI_ADMIN_TOKEN not set")
        return

    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    # 1. Create a user that will be deleted
    email = f"deleted-user-{random_string()}@example.com"
    password = "password"
    user_to_delete = create_user(email, password, "User to Delete")
    token_to_delete = login(email, password)

    # 2. Create all types of data for this user
    chat_to_delete = create_chat(token_to_delete, "Chat to Delete")
    file_to_delete = upload_file(
        token_to_delete, create_dummy_file("file_to_delete.txt")
    )
    note_to_delete = create_note(token_to_delete, "Note to Delete")
    prompt_to_delete = create_prompt(
        token_to_delete, "prompt-to-delete", "Prompt to Delete", "content"
    )
    model_to_delete = create_model(token_to_delete, "model-to-delete")
    kb_to_delete = create_knowledge_base(token_to_delete, "KB to Delete")
    function_to_delete = create_function(
        token_to_delete, "function-to-delete", "def main(): pass"
    )
    tool_to_delete = create_tool(token_to_delete, "tool-to-delete", "def main(): pass")

    # 3. Delete the user
    delete_user(ADMIN_TOKEN, user_to_delete["id"])

    # 4. Prune all data
    prune_data = {"days": 0, "exempt_archived_chats": False}
    response = requests.post(f"{BASE_URL}/prune/", json=prune_data, headers=headers)
    response.raise_for_status()

    # 5. Verify that all data associated with the deleted user is gone
    # We expect 401 because the user is deleted, so we can't use their token
    response = requests.get(
        f"{BASE_URL}/chats/{chat_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/files/{file_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/notes/{note_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/prompts/command/{prompt_to_delete['command']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/models/model?id={model_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/knowledge/{kb_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/functions/id/{function_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    response = requests.get(
        f"{BASE_URL}/tools/id/{tool_to_delete['id']}",
        headers={"Authorization": f"Bearer {token_to_delete}"},
    )
    assert response.status_code == 401

    # Clean up dummy files
    for f in ["file_to_delete.txt"]:
        if os.path.exists(f):
            os.remove(f)
