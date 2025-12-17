# Image Storage Analysis for Open WebUI

## Issue Summary
GitHub Discussion [#13122](https://github.com/open-webui/open-webui/discussions/13122) identifies a critical performance issue:
- Large base64 images embedded in session data cause slow load times
- Base64 encoding adds ~33% overhead
- No browser caching for images
- Images are transmitted multiple times in session JSON

## Current Implementation Analysis

### 1. Response Images (Assistant Messages)

#### Current System with ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION

**Location**: `backend/open_webui/env.py:570-573`
```python
ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION = (
    os.environ.get("ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION", "False").lower()
    == "true"
)
```

**How It Works**:

1. **Processing Location**: `backend/open_webui/utils/middleware.py:2697-2700`
   - During streaming response processing, if enabled, the middleware calls `convert_markdown_base64_images()` on response content

2. **Conversion Function**: `backend/open_webui/utils/files.py:47-57`
   ```python
   def convert_markdown_base64_images(request, content: str, metadata, user):
       def replace(match):
           base64_string = match.group(2)
           MIN_REPLACEMENT_URL_LENGTH = 1024
           if len(base64_string) > MIN_REPLACEMENT_URL_LENGTH:
               url = get_image_url_from_base64(request, base64_string, metadata, user)
               if url:
                   return f"![{match.group(1)}]({url})"
           return match.group(0)

       return MARKDOWN_IMAGE_URL_PATTERN.sub(replace, content)
   ```

3. **Process Flow**:
   - Detects markdown images: `![alt text](data:image/png;base64,....)`
   - If base64 string > 1024 chars:
     - Extracts image data
     - Uploads as file via `upload_image()` → `upload_file_handler()`
     - Replaces base64 with URL: `![alt text](/api/v1/files/{id}/content)`

4. **Storage**:
   - **Physical Storage**: Via `Storage.upload_file()` (configurable storage provider)
   - **Database Record**: `Files` table in `backend/open_webui/models/files.py`
     ```python
     class File(Base):
         id = Column(String, primary_key=True, unique=True)
         user_id = Column(String)
         hash = Column(Text, nullable=True)
         filename = Column(Text)
         path = Column(Text, nullable=True)
         data = Column(JSON, nullable=True)
         meta = Column(JSON, nullable=True)  # Contains: name, content_type, size
         access_control = Column(JSON, nullable=True)
         created_at = Column(BigInteger)
         updated_at = Column(BigInteger)
     ```

### 2. User Input Images (User Messages)

#### Current System

**Upload Flow**:

1. **Frontend**: `src/lib/apis/files/index.ts:4-95`
   - User uploads file via `uploadFile(token, file, metadata, process)`
   - Sends multipart form data to `/api/v1/files/`

2. **Backend**: `backend/open_webui/routers/files.py:170-290`
   ```python
   def upload_file_handler(request, file, metadata, process, user):
       # Generate unique ID
       id = str(uuid.uuid4())
       filename = f"{id}_{file.filename}"

       # Store file physically
       contents, file_path = Storage.upload_file(file.file, filename, headers)

       # Store metadata in database
       file_item = Files.insert_new_file(user.id, FileForm(...))

       return file_item  # Contains: id, filename, path, meta
   ```

3. **Message Storage**: `backend/open_webui/models/chats.py:26-76`
   ```python
   class Chat(Base):
       id = Column(String, primary_key=True)
       user_id = Column(String)
       title = Column(Text)
       chat = Column(JSON)  # Contains: messages, history
       created_at = Column(BigInteger)
       updated_at = Column(BigInteger)
   ```

**Problem**: User messages with images are currently stored as:
```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "What's in this image?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KG..."}}
  ]
}
```

This causes:
- Entire base64 string stored in chat JSON
- Sent to frontend on every chat load
- No caching
- Large payload sizes (session JSON can be 100MB+)

### 3. Access Control

**Location**: `backend/open_webui/routers/files.py:65-98`

**Access Granted If**:
1. User owns the file (`file.user_id == user.id`)
2. User is admin (`user.role == "admin"`)
3. File is shared via:
   - Knowledge bases (user has access through ownership or group membership)
   - Channels (user is a member)

**Implementation**: `backend/open_webui/routers/files.py:545-612`
```python
@router.get("/{id}/content")
async def get_file_content_by_id(id: str, user=Depends(get_verified_user)):
    file = Files.get_file_by_id(id)

    if (file.user_id == user.id
        or user.role == "admin"
        or has_access_to_file(id, "read", user)):
        # Return file content
        return FileResponse(file_path, headers=headers, media_type=content_type)
    else:
        raise HTTPException(status_code=404)
```

## Current Status of ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION

**Issue Author's Finding**: Even with this flag set to `True`, session JSON still contains large base64 images.

**Why**:
- The flag only converts **response images** (from assistant messages)
- It does NOT convert **user input images**
- User-uploaded images are still embedded as base64 in message content

## Solution Approach

### Phase 1: Fix User Input Images (Not Yet Implemented)

**Goal**: Convert user message images to use file URLs instead of base64

**Implementation Plan**:

1. **Create Conversion Function** (similar to response images):
   ```python
   # In backend/open_webui/utils/files.py
   def convert_message_content_images(request, message_content, metadata, user):
       """
       Convert base64 images in message content to file URLs
       Handles both string content and array content with image_url types
       """
       if isinstance(message_content, str):
           return convert_markdown_base64_images(request, message_content, metadata, user)

       elif isinstance(message_content, list):
           converted_content = []
           for item in message_content:
               if item.get("type") == "image_url":
                   url = item["image_url"]["url"]
                   if url.startswith("data:image/"):
                       # Convert base64 to file URL
                       file_url = get_image_url_from_base64(request, url, metadata, user)
                       if file_url:
                           item["image_url"]["url"] = file_url
               converted_content.append(item)
           return converted_content

       return message_content
   ```

2. **Apply Conversion in Chat Save/Update**:
   - Location: `backend/open_webui/routers/chats.py` or `backend/open_webui/utils/middleware.py`
   - Hook into message storage before saving to database
   - Process all messages in chat history

3. **Environment Variable**:
   ```python
   # In backend/open_webui/env.py
   ENABLE_CHAT_INPUT_BASE64_IMAGE_URL_CONVERSION = (
       os.environ.get("ENABLE_CHAT_INPUT_BASE64_IMAGE_URL_CONVERSION", "True").lower()
       == "true"
   )
   ```

4. **Migration for Existing Chats** (Optional):
   - Create migration script to convert existing base64 images in chat history
   - Can be run as background job or on-demand

### Phase 2: Optimize Frontend File Upload

**Current Issue**: User pastes/uploads image → converted to base64 → sent to backend

**Better Approach**:
1. Upload image as file immediately upon paste/upload
2. Store file ID in message
3. Convert to `/api/v1/files/{id}/content` URL before sending to LLM
4. Frontend displays image from URL (cacheable)

### Phase 3: Lazy Loading for Chat History

**Implementation**:
1. Load chat metadata first (title, timestamps, etc.)
2. Load messages progressively as user scrolls
3. Load images on-demand (already supported if using file URLs)

## Files to Modify

### Backend Changes:

1. **`backend/open_webui/env.py`**
   - Add `ENABLE_CHAT_INPUT_BASE64_IMAGE_URL_CONVERSION` variable

2. **`backend/open_webui/utils/files.py`**
   - Add `convert_message_content_images()` function
   - Extend to handle OpenAI message format with image_url types

3. **`backend/open_webui/utils/middleware.py`** OR **`backend/open_webui/routers/chats.py`**
   - Hook conversion before saving messages to database
   - Apply to both new messages and chat updates

4. **`backend/open_webui/models/chats.py`** (Optional)
   - Add helper method to convert images in chat history

### Frontend Changes:

1. **`src/lib/components/chat/MessageInput.svelte`**
   - Upload images as files immediately on paste/select
   - Store file URLs instead of base64 in message content

2. **`src/lib/components/chat/Chat.svelte`**
   - Ensure images are displayed from URLs (not base64)
   - Leverage browser caching

## Expected Performance Improvements

### Before:
- Session JSON: 100MB+ with multiple large images
- Load time: Several seconds
- Memory: High (all images in memory)
- Network: Re-download images every session load
- Browser caching: None

### After:
- Session JSON: <1MB (only file URLs)
- Load time: <1 second for text, images load progressively
- Memory: Low (images loaded on-demand)
- Network: Images cached by browser
- Browser caching: Full support

## Access Control Implications

**Current System is Secure**:
- File URLs like `/api/v1/files/{id}/content` require authentication
- Access control enforced on every request
- User must own file or have shared access

**No Security Changes Needed**:
- Same access control applies whether image is base64 or URL
- File IDs are UUIDs (not guessable)
- Failed access returns 404 (not 403) to prevent enumeration

## Compatibility Considerations

1. **Backward Compatibility**:
   - Existing chats with base64 images will still work
   - Conversion can be opt-in via environment variable
   - Gradual migration possible

2. **Export/Import**:
   - Chat exports may need to bundle images separately
   - Or convert URLs back to base64 for portability

3. **Shared Chats**:
   - Need to ensure shared chat viewers can access images
   - May need special handling for public shares

## Recommendation

**Priority 1**: Implement user input image conversion
- Most impactful change
- Solves the core issue from GitHub discussion
- Relatively straightforward implementation

**Priority 2**: Optimize frontend upload flow
- Improves UX
- Reduces client-side processing

**Priority 3**: Add lazy loading
- Further performance optimization
- Can be added incrementally

## Testing Plan

1. **Unit Tests**:
   - Test `convert_message_content_images()` with various input formats
   - Test file upload and URL generation

2. **Integration Tests**:
   - Upload image in chat
   - Verify stored as file URL in database
   - Verify image displays correctly
   - Verify access control works

3. **Performance Tests**:
   - Measure session load time before/after
   - Measure memory usage
   - Test with various image sizes

4. **Migration Tests**:
   - Test conversion of existing chats
   - Verify no data loss

## References

- GitHub Discussion: https://github.com/open-webui/open-webui/discussions/13122
- Related Issue: #11934 (similar issue in different context)
- Environment Variables: `backend/open_webui/env.py:570-573`
- File Upload: `backend/open_webui/routers/files.py:170-290`
- Image Conversion: `backend/open_webui/utils/files.py:47-57`
- Middleware: `backend/open_webui/utils/middleware.py:2697-2700`
