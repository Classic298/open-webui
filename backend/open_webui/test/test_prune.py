import os
import uuid
import time
import shutil
import random
import string
import requests
import json

BASE_URL = "http://localhost:8080/api/v1"
DATA_DIR = os.environ.get("DATA_DIR", "/app/backend/data")


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


def delete_user(token, user_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.delete(f"{BASE_URL}/users/{user_id}", headers=headers)
    response.raise_for_status()


def get_db_size():
    return os.path.getsize(f"{DATA_DIR}/webui.db")


def get_vector_db_size():
    return sum(
        f.stat().st_size
        for f in os.scandir(f"{DATA_DIR}/vector_db")
        if f.is_file()
    )


def test_prune_data_and_check_db_size():
    ADMIN_TOKEN = os.environ.get("OPEN_WEBUI_ADMIN_TOKEN")
    if not ADMIN_TOKEN:
        print("Skipping API test: OPEN_WEBUI_ADMIN_TOKEN not set")
        return

    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    # 1. Get initial DB sizes
    initial_db_size = get_db_size()
    initial_vector_db_size = get_vector_db_size()

    # 2. Create a user and some data
    email = f"prune-test-{random_string()}@example.com"
    password = "password"
    user = create_user(email, password, "Prune Test User")
    token = login(email, password)

    chat1 = create_chat(token, "Chat 1")
    file1 = upload_file(token, create_dummy_file("file1.txt", size=1024 * 1024))

    # 3. Prune all data
    prune_data = {"days": 0, "exempt_archived_chats": False}
    response = requests.post(f"{BASE_URL}/prune/", json=prune_data, headers=headers)
    response.raise_for_status()

    # 4. Get final DB sizes
    final_db_size = get_db_size()
    final_vector_db_size = get_vector_db_size()

    # 5. Assert that the DB sizes have decreased
    assert final_db_size < initial_db_size
    assert final_vector_db_size < initial_vector_db_size

    # 6. Clean up the user
    delete_user(ADMIN_TOKEN, user["id"])

    # Clean up dummy files
    for f in ["file1.txt"]:
        if os.path.exists(f):
            os.remove(f)
