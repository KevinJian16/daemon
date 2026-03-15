# OpenClaw Daemon Scene Endpoints Documentation

## POST /scenes/{scene}/chat

### Description

This endpoint is used to send a chat message to a specific scene.

### Request

- **Method:** POST
- **URL:** `/scenes/{scene}/chat`
- **Headers:**
  - `Content-Type: application/json`
- **Body:**
  ```json
  {
    "message": "string",
    "sender": "string"
  }
  ```

### Response

- **Status Codes:**
  - `200 OK`: The message was successfully sent.
  - `400 Bad Request`: The request was invalid.
  - `404 Not Found`: The specified scene does not exist.
  - `500 Internal Server Error`: An unexpected error occurred.
- **Body:**
  ```json
  {
    "status": "success|error",
    "message": "string"
  }
  ```

## GET /scenes/{scene}/panel

### Description

This endpoint is used to retrieve the panel information for a specific scene.

### Request

- **Method:** GET
- **URL:** `/scenes/{scene}/panel`
- **Headers:**
  - `Accept: application/json`

### Response

- **Status Codes:**
  - `200 OK`: The panel information was successfully retrieved.
  - `404 Not Found`: The specified scene does not exist.
  - `500 Internal Server Error`: An unexpected error occurred.
- **Body:**
  ```json
  {
    "panel": {
      "title": "string",
      "description": "string",
      "controls": [
        {"name": "string", "type": "string", "value": "string"}
      ]
    }
  }
  ```
