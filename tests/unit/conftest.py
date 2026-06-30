"""单元测试 fixture — 不依赖真实 Spotify API 凭据。"""

import pytest


@pytest.fixture(scope="session")
def base_url():
    return "https://api.spotify.com/v1"


@pytest.fixture(scope="session")
def auth_token():
    """单元测试用假 token，不请求真实 API。"""
    return "mock_token_for_unit_tests"


@pytest.fixture
def minimal_spec():
    """最小化的 OpenAPI 规范，作为 $ref 解析测试的输入。"""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0"},
        "paths": {
            "/artists/{id}": {
                "get": {
                    "operationId": "get-an-artist",
                    "summary": "Get an artist",
                    "tags": ["Artists"],
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"$ref": "#/components/schemas/ArtistId"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Successful",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ArtistObject",
                                    }
                                }
                            },
                        },
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                    },
                }
            },
            "/albums/{id}": {
                "get": {
                    "operationId": "get-an-album",
                    "summary": "Get an album",
                    "tags": ["Albums"],
                    "parameters": [],
                    "responses": {
                        "200": {
                            "description": "Successful",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/AlbumObject",
                                    }
                                }
                            },
                        },
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ArtistId": {"type": "string", "example": "0TnOYISbd1XYRBk9myaseg"},
                "ArtistObject": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "external_urls": {
                            "$ref": "#/components/schemas/ExternalUrls",
                        },
                    },
                },
                "AlbumObject": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "artists": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/ArtistObject"},
                        },
                    },
                },
                "ExternalUrls": {
                    "type": "object",
                    "properties": {"spotify": {"type": "string"}},
                },
                "CircularA": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/components/schemas/CircularB"},
                    },
                },
                "CircularB": {
                    "type": "object",
                    "properties": {
                        "parent": {"$ref": "#/components/schemas/CircularA"},
                    },
                },
            },
            "responses": {
                "Unauthorized": {
                    "description": "Unauthorized",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "error": {"type": "object"},
                                },
                            },
                        }
                    },
                },
            },
        },
    }
