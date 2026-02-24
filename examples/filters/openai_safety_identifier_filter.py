"""
title: OpenAI Safety Identifier Filter
author: open-webui
version: 0.1.0
license: MIT
description: Injects a hashed safety_identifier into OpenAI API requests per their abuse-prevention guidelines.
"""

import hashlib


class Filter:
    def __init__(self):
        pass

    def inlet(self, body: dict, __user__: dict = None) -> dict:
        if __user__ and __user__.get("email"):
            identifier = hashlib.sha256(__user__["email"].encode()).hexdigest()
        elif __user__ and __user__.get("id"):
            identifier = hashlib.sha256(__user__["id"].encode()).hexdigest()
        else:
            session_id = body.get("metadata", {}).get("session_id", "anonymous")
            identifier = hashlib.sha256(session_id.encode()).hexdigest()

        body["safety_identifier"] = identifier
        return body
