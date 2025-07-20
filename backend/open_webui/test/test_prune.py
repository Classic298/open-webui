import os
import uuid
import time
import shutil
import random
import string
import requests
import json

# It's better to get this from an environment variable or a config file
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


def create_chat(token, title, archived=False, old=False):
    headers = {"Authorization": f"Bearer {token}"}
    chat_data = {"chat": {"title": title}}
    response = requests.post(f"{BASE_URL}/chats/new", json=chat_data, headers=headers)
    response.raise_for_status()
    chat = response.json()

    if archived:
        response = requests.post(
            f"{BASE_URL}/chats/{chat['id']}/archive", headers=headers
        )
        response.raise_for_status()
        chat = response.json()

    # This part is tricky without direct DB access. We'll have to assume that if we can't
    # modify the updated_at timestamp, we can't test the date-based pruning reliably
    # in a pure API-based test. A potential workaround would be to have a separate
    # endpoint for testing purposes to modify timestamps, but that's out of scope here.
    # For now, we'll just have to trust that the days parameter works as implemented.

    return chat


def upload_file(token, file_name, content_type="text/plain"):
    headers = {"Authorization": f"Bearer {token}"}
    with open(file_name, "rb") as f:
        files = {"file": (file_name, f.read(), content_type)}
        response = requests.post(f"{BASE_URL}/files/", files=files, headers=headers)
    response.raise_for_status()
    return response.json()


def associate_file_with_chat(token, chat, file):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/chats/{chat['id']}", headers=headers)
    response.raise_for_status()
    chat_model = response.json()

    chat_model["chat"]["history"] = {
        "messages": {
            str(uuid.uuid4()): {
                "content": "test message",
                "file": {"id": file["id"]},
            }
        }
    }
    response = requests.post(
        f"{BASE_URL}/chats/{chat['id']}",
        json={"chat": chat_model["chat"]},
        headers=headers,
    )
    response.raise_for_status()
    return response.json()


def delete_user(token, user_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.delete(f"{BASE_URL}/users/{user_id}", headers=headers)
    response.raise_for_status()


def test_prune_data_api_only():
    # This test assumes the server is running and accessible at BASE_URL.
    # It also assumes that the user running the test has provided a valid admin JWT token.
    ADMIN_TOKEN = os.environ.get("OPEN_WEBUI_ADMIN_TOKEN")
    if not ADMIN_TOKEN:
        print("Skipping API test: OPEN_WEBUI_ADMIN_TOKEN not set")
        return

    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    # 1. Create a user and some data
    email = f"prune-test-{random_string()}@example.com"
    password = "password"
    user = create_user(email, password, "Prune Test User")
    token = login(email, password)

    chat1 = create_chat(token, "Chat 1")
    chat2 = create_chat(token, "Chat 2 (Archived)", archived=True)
    chat3 = create_chat(token, "Chat 3 (To be deleted)")

    file1 = upload_file(token, create_dummy_file("file1.txt"))
    file2 = upload_file(token, create_dummy_file("file2.txt"))
    file3 = upload_file(token, create_dummy_file("orphaned.txt"))

    associate_file_with_chat(token, chat1, file1)
    associate_file_with_chat(token, chat2, file2)

    # Delete a chat, orphaning its file
    requests.delete(f"{BASE_URL}/chats/{chat3['id']}", headers=headers)

    # 2. Prune all non-archived data
    prune_data = {"days": 0, "exempt_archived_chats": True}
    response = requests.post(f"{BASE_URL}/prune/", json=prune_data, headers=headers)
    response.raise_for_status()

    # 3. Verify the results
    # Chat 1 should be deleted
    response = requests.get(f"{BASE_URL}/chats/{chat1['id']}", headers=headers)
    assert response.status_code == 401

    # Chat 2 (archived) should still exist
    response = requests.get(f"{BASE_URL}/chats/{chat2['id']}", headers=headers)
    assert response.status_code == 200

    # File 1 (from Chat 1) should be deleted
    response = requests.get(f"{BASE_URL}/files/{file1['id']}", headers=headers)
    assert response.status_code == 404

    # File 2 (from archived Chat 2) should still exist
    response = requests.get(f"{BASE_URL}/files/{file2['id']}", headers=headers)
    assert response.status_code == 200

    # Orphaned file 3 should be deleted
    response = requests.get(f"{BASE_URL}/files/{file3['id']}", headers=headers)
    assert response.status_code == 404

    # 4. Prune everything
    prune_data = {"days": 0, "exempt_archived_chats": False}
    response = requests.post(f"{BASE_URL}/prune/", json=prune_data, headers=headers)
    response.raise_for_status()

    # 5. Verify everything is gone
    response = requests.get(f"{BASE_URL}/chats/{chat2['id']}", headers=headers)
    assert response.status_code == 401

    response = requests.get(f"{BASE_URL}/files/{file2['id']}", headers=headers)
    assert response.status_code == 404

    # 6. Clean up the user
    delete_user(ADMIN_TOKEN, user["id"])

    # Clean up dummy files
    for f in ["file1.txt", "file2.txt", "orphaned.txt"]:
        if os.path.exists(f):
            os.remove(f)
