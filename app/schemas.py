from pydantic import BaseModel


class CreateChatBody(BaseModel):
    title: str = "New Chat"
    model: str | None = None
    duo_mode: bool | None = None


class UpdateChatBody(BaseModel):
    title: str | None = None
    model: str | None = None
    starred: bool | None = None
    duo_mode: bool | None = None


class UpdateSettingsBody(BaseModel):
    provider: str = "nim"
    key: str | None = None
    base_url: str | None = None
    account_id: str | None = None
    temperature: float | None = None


class DocumentAttachment(BaseModel):
    name: str
    text: str


class SendMessageBody(BaseModel):
    content: str = ""
    model: str | None = None
    images: list[str] | None = None
    documents: list[DocumentAttachment] | None = None
    web_search: bool = False
    client_time: str | None = None
    skip_user_save: bool = False
    duo_side: int = 0


class SaveAssistantBody(BaseModel):
    content: str
    timing_data: str | None = None


class RegenerateBody(BaseModel):
    model: str | None = None
    web_search: bool = False
    client_time: str | None = None
    overwrite_message_id: str | None = None
    duo_side: int = 0


class VerifyKeyBody(BaseModel):
    provider: str = "nim"
    key: str
    base_url: str
    account_id: str | None = None


class WarmupBody(BaseModel):
    model: str | None = None
