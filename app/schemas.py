from pydantic import BaseModel


class ApiRequest(BaseModel):
    """Base class for public API request payloads."""


class CreateChatBody(ApiRequest):
    """Payload used to create a conversation."""
    title: str = "New Chat"
    model: str | None = None
    model2: str | None = None
    duo_mode: bool | None = None
    persona: str | None = None
    persona2: str | None = None


class UpdateChatBody(ApiRequest):
    """Fields that may be changed on an existing conversation."""
    title: str | None = None
    model: str | None = None
    model2: str | None = None
    starred: bool | None = None
    duo_mode: bool | None = None
    persona: str | None = None
    persona2: str | None = None


class UpdateSettingsBody(ApiRequest):
    """Provider connection settings supplied by the settings UI."""
    provider: str = "nim"
    key: str | None = None
    base_url: str | None = None
    account_id: str | None = None
    temperature: float | None = None


class ImageAttachment(ApiRequest):
    """An inline image sent as a data URL."""
    name: str = "image"
    dataUrl: str


class DocumentAttachment(ApiRequest):
    """Extracted text from an uploaded document."""
    name: str
    text: str


class SendMessageBody(ApiRequest):
    """Payload for a streamed assistant response."""
    content: str = ""
    model: str | None = None
    images: list[str | ImageAttachment] | None = None
    documents: list[DocumentAttachment] | None = None

    web_search: bool = False
    client_time: str | None = None
    skip_user_save: bool = False
    duo_side: int = 0
    persona: str | None = None


class SaveAssistantBody(ApiRequest):
    """Payload used to persist a client-stopped assistant response."""
    content: str
    timing_data: str | None = None


class RegenerateBody(ApiRequest):
    """Options used to regenerate an assistant response."""
    model: str | None = None
    web_search: bool = False
    client_time: str | None = None
    overwrite_message_id: str | None = None
    duo_side: int = 0
    persona: str | None = None


class VerifyKeyBody(ApiRequest):
    """Provider credentials to validate without persisting them."""
    provider: str = "nim"
    key: str
    base_url: str
    account_id: str | None = None


class WarmupBody(ApiRequest):
    """Optional model selection for a warm-up request."""
    model: str | None = None
