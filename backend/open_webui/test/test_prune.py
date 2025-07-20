import os
import uuid
import time
import shutil
import random
import string
from fastapi.testclient import TestClient

from open_webui.main import app
from open_webui.internal.db import get_db
from open_webui.models.chats import Chat

client = TestClient(app)


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
    response = client.post("/api/v1/users/create", json=user_data)
    assert response.status_code == 200
    return response.json()


def login(email, password):
    auth_data = {"email": email, "password": password}
    response = client.post("/api/v1/auths/login", json=auth_data)
    assert response.status_code == 200
    return response.json()["token"]


def create_chat(token, title, archived=False, old=False):
    headers = {"Authorization": f"Bearer {token}"}
    chat_data = {"chat": {"title": title}}
    response = client.post("/api/v1/chats/new", json=chat_data, headers=headers)
    assert response.status_code == 200
    chat = response.json()

    if archived:
        response = client.post(f"/api/v1/chats/{chat['id']}/archive", headers=headers)
        assert response.status_code == 200
        chat = response.json()

    if old:
        with get_db() as db:
            chat_to_update = db.get(Chat, chat["id"])
            chat_to_update.updated_at = int(time.time()) - (100 * 86400)  # 100 days old
            db.commit()
            db.refresh(chat_to_update)
            chat = chat_to_update

    return chat


def upload_file(token, file_name, content_type="text/plain"):
    headers = {"Authorization": f"Bearer {token}"}
    with open(file_name, "rb") as f:
        files = {"file": (file_name, f.read(), content_type)}
        response = client.post("/api/v1/files/", files=files, headers=headers)
    assert response.status_code == 200
    return response.json()


def associate_file_with_chat(token, chat, file):
    headers = {"Authorization": f"Bearer {token}"}
    chat_model = client.get(f"/api/v1/chats/{chat['id']}", headers=headers).json()

    chat_model["chat"]["history"] = {
        "messages": {
            str(uuid.uuid4()): {
                "content": "test message",
                "file": {"id": file["id"]},
            }
        }
    }
    response = client.post(
        f"/api/v1/chats/{chat['id']}",
        json={"chat": chat_model["chat"]},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()


def delete_user(token, user_id):
    headers = {"Authorization": f"Bearer {token}"}
    response = client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert response.status_code == 200


def test_prune_data_very_extensively():
    # Clean up from previous tests
    if os.path.exists("uploads"):
        shutil.rmtree("uploads")

    # 1. Create a variety of users
    admin_user = create_user("admin@test.com", "password", "Admin User")
    client.post(f"/api/v1/users/{admin_user['id']}/update", json={"role": "admin"}, headers={"Authorization": f"Bearer {login('admin@test.com', 'password')}"})
    admin_token = login("admin@test.com", "password")


    users = [create_user(f"user{i}@test.com", "password", f"User {i}") for i in range(5)]
    tokens = [login(f"user{i}@test.com", "password") for i in range(5)]

    # 2. Create a diverse set of chats
    chats = []
    for i, token in enumerate(tokens):
        # Regular chats
        chats.append(create_chat(token, f"User {i} Chat 1"))
        # Archived chats
        chats.append(create_chat(token, f"User {i} Chat 2 (Archived)", archived=True))
        # Old chats
        chats.append(create_chat(token, f"User {i} Chat 3 (Old)", old=True))
        # Old and archived chats
        chats.append(
            create_chat(token, f"User {i} Chat 4 (Old, Archived)", archived=True, old=True)
        )
        # Chats with no files
        chats.append(create_chat(token, f"User {i} Chat 5 (No Files)"))

    # 3. Create and upload a variety of files
    file_types = {
        "test.txt": "text/plain",
        "test.pdf": "application/pdf",
        "test.jpg": "image/jpeg",
        "test.png": "image/png",
        "test.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "test.mp3": "audio/mpeg",
        "test.webm": "video/webm",
        "weird_name_!@#$%.dat": "application/octet-stream",
        "file with spaces.txt": "text/plain",
    }

    files = []
    for i, token in enumerate(tokens):
        for file_name, content_type in file_types.items():
            dummy_file = create_dummy_file(file_name)
            files.append(upload_file(token, dummy_file, content_type))
            os.remove(dummy_file)

    # 4. Associate files with chats in various ways
    for i, chat in enumerate(chats):
        if "No Files" not in chat["title"]:
            # Associate a random number of files with each chat
            for _ in range(random.randint(1, 3)):
                file_to_associate = random.choice(files)
                token_index = int(chat["user_id"][-1])
                associate_file_with_chat(tokens[token_index], chat, file_to_associate)

    # 5. Create orphaned files
    orphaned_files = []
    for i, token in enumerate(tokens):
        dummy_file = create_dummy_file(f"orphaned_{i}.txt")
        orphaned_files.append(upload_file(token, dummy_file))
        os.remove(dummy_file)

    # 6. Delete a user, orphaning all their chats and files
    deleted_user_id = users[4]["id"]
    delete_user(admin_token, deleted_user_id)

    # 7. Start pruning tests
    # Scenario A: Prune nothing (days = 9999)
    prune_data = {"days": 9999, "exempt_archived_chats": True}
    response = client.post("/api/v1/prune/", json=prune_data, headers=admin_token)
    assert response.status_code == 200

    # Assert that no chats were deleted (except the deleted user's)
    for chat in chats:
        if chat["user_id"] != deleted_user_id:
            response = client.get(
                f"/api/v1/chats/{chat['id']}",
                headers={"Authorization": f"Bearer {tokens[int(chat['user_id'][-1])]}"},
            )
            assert response.status_code == 200

    # Scenario B: Prune old chats, exempting archived
    prune_data = {"days": 60, "exempt_archived_chats": True}
    response = client.post("/api/v1/prune/", json=prune_data, headers=admin_token)
    assert response.status_code == 200

    for chat in chats:
        if chat["user_id"] != deleted_user_id:
            token = tokens[int(chat["user_id"][-1])]
            if "Old" in chat["title"] and "Archived" not in chat["title"]:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 401
            else:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 200

    # Scenario C: Prune old chats, including archived
    prune_data = {"days": 60, "exempt_archived_chats": False}
    response = client.post("/api/v1/prune/", json=prune_data, headers=admin_token)
    assert response.status_code == 200

    for chat in chats:
        if chat["user_id"] != deleted_user_id:
            token = tokens[int(chat["user_id"][-1])]
            if "Old" in chat["title"]:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 401
            else:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 200

    # Scenario D: Prune all non-archived chats
    prune_data = {"days": 0, "exempt_archived_chats": True}
    response = client.post("/api/v1/prune/", json=prune_data, headers=admin_token)
    assert response.status_code == 200

    for chat in chats:
        if chat["user_id"] != deleted_user_id:
            token = tokens[int(chat["user_id"][-1])]
            if "Archived" not in chat["title"]:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 401
            else:
                response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 200

    # Scenario E: Prune everything
    prune_data = {"days": 0, "exempt_archived_chats": False}
    response = client.post("/api/v1/prune/", json=prune_data, headers=admin_token)
    assert response.status_code == 200

    # Assert that all chats and files are gone
    for chat in chats:
        if chat["user_id"] != deleted_user_id:
            token = tokens[int(chat["user_id"][-1])]
            response = client.get(f"/api/v1/chats/{chat['id']}", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 401

    for file in files:
         if file["user_id"] != deleted_user_id:
            token = tokens[int(file["user_id"][-1])]
            response = client.get(f"/api/v1/files/{file['id']}", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 404

    for file in orphaned_files:
        if file["user_id"] != deleted_user_id:
            token = tokens[int(file["user_id"][-1])]
            response = client.get(f"/api/v1/files/{file['id']}", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 404

    # Final cleanup
    if os.path.exists("uploads"):
        shutil.rmtree("uploads")
